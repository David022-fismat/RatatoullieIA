"""
Escolha do provedor de LLM: Anthropic (pago) ou provedores com cota grátis (Gemini, Groq).

A escolha é feita por variáveis de ambiente, nesta ordem:
  LLM_PROVEDOR=gemini|groq|anthropic   (opcional: força um provedor)
  GEMINI_API_KEY   -> Google Gemini (grátis em aistudio.google.com/apikey)
  GROQ_API_KEY     -> Groq (grátis em console.groq.com/keys)
  ANTHROPIC_API_KEY -> Anthropic (pago, console.anthropic.com)

Gemini e Groq falam o formato da OpenAI ("chat completions"). A classe ClienteOpenAICompat
traduz esse formato para o da Anthropic, que é o que o Orquestrador usa. Assim o Orquestrador
não muda nada: ele chama cliente.messages.create(...) igual, seja qual for o provedor.
Não precisa instalar nada além da biblioteca padrão do Python.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from types import SimpleNamespace as NS

PROVEDORES = {
    # nome: (variável da chave, endereço da API, modelo padrão)
    "gemini": ("GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai",
               "gemini-3.8-flash"),
    "groq": ("GROQ_API_KEY", "https://api.groq.com/openai/v1", "openai/gpt-oss-120b"),
}
# Modelos reserva: se o principal estiver sobrecarregado (ou não existir na conta), tenta o próximo.
RESERVAS = {
    "gemini": ["gemini-3.5-flash", "gemini-3.5-flash-lite"],   # 2.5 não aceita contas novas
    "groq": [],
}


def provedor_disponivel():
    """Devolve o nome do provedor a usar, ou None se não houver chave nenhuma."""
    forcado = os.getenv("LLM_PROVEDOR", "").lower()
    if forcado:
        return forcado
    for nome, (var, _, _) in PROVEDORES.items():
        if os.getenv(var):
            return nome
    return "anthropic" if os.getenv("ANTHROPIC_API_KEY") else None


def criar_cliente(provedor, chave=None):
    """Cliente com a interface cliente.messages.create(...) da Anthropic.
    chave: opcional; se não vier, usa a variável de ambiente do provedor."""
    if provedor == "anthropic":
        import anthropic
        cliente = anthropic.Anthropic(api_key=chave) if chave else anthropic.Anthropic()
        return cliente, os.getenv("MODELO_ORQUESTRADOR", "claude-haiku-5-5")
    var, url, modelo = PROVEDORES[provedor]
    chave = chave or os.getenv(var)
    if not chave:
        raise RuntimeError(f"Defina {var} para usar o provedor {provedor}.")
    return ClienteOpenAICompat(url, chave, reservas=RESERVAS.get(provedor, [])), \
        os.getenv("MODELO_ORQUESTRADOR", modelo)


def funcao_texto(provedor):
    """Função prompt -> texto, para o Montador no modo LLM."""
    if provedor == "anthropic":
        from .montador import llm_anthropic
        return llm_anthropic
    cliente, modelo = criar_cliente(provedor)

    def chamar(prompt):
        r = cliente.messages.create(model=modelo, max_tokens=2000, system="",
                                    messages=[{"role": "user", "content": prompt}])
        return "".join(b.text for b in r.content if b.type == "text")
    return chamar


# ---------------------------------------------------------------------- tradução de formatos
def _para_openai(system, messages, tools):
    saida = [{"role": "system", "content": system}] if system else []
    for m in messages:
        c = m["content"]
        if isinstance(c, str):
            saida.append({"role": m["role"], "content": c})
        elif m["role"] == "assistant":
            texto = "".join(b.get("text", "") for b in c if b["type"] == "text")
            chamadas = []
            for b in c:
                if b["type"] != "tool_use":
                    continue
                chamada = {"id": b["id"], "type": "function",
                           "function": {"name": b["name"], "arguments": json.dumps(b["input"], ensure_ascii=False)}}
                if b.get("extra_content"):              # Gemini 3: devolve a "assinatura do raciocínio"
                    chamada["extra_content"] = b["extra_content"]
                chamadas.append(chamada)
            msg = {"role": "assistant", "content": texto or None}
            if chamadas:
                msg["tool_calls"] = chamadas
            saida.append(msg)
        else:                                   # resultados de ferramentas
            for b in c:
                if b["type"] == "tool_result":
                    saida.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": b["content"]})
                elif b["type"] == "text":
                    saida.append({"role": "user", "content": b["text"]})
    corpo = {"messages": saida}
    if tools:
        corpo["tools"] = [{"type": "function", "function": {
            "name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
            for t in tools]
    return corpo


def _da_openai(resposta):
    msg = resposta["choices"][0]["message"]
    blocos = []
    if msg.get("content"):
        blocos.append(NS(type="text", text=msg["content"]))
    for i, c in enumerate(msg.get("tool_calls") or []):
        try:
            args = json.loads(c["function"].get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        bloco = NS(type="tool_use", id=c.get("id") or f"chamada_{i}", name=c["function"]["name"], input=args)
        if c.get("extra_content"):                      # ex.: {"google": {"thought_signature": "..."}}
            bloco.extra_content = c["extra_content"]    # precisa voltar igual no próximo pedido
        blocos.append(bloco)
    parou = "tool_use" if any(b.type == "tool_use" for b in blocos) else "end_turn"
    return NS(content=blocos or [NS(type="text", text="")], stop_reason=parou)


class ProvedorIndisponivel(RuntimeError):
    """Erro temporário que não passou nem tentando de novo (ou modelo inexistente): vale trocar de modelo."""


class ClienteOpenAICompat:
    def __init__(self, url, chave, timeout=60, reservas=()):
        self.url, self.chave, self.timeout = url.rstrip("/"), chave, timeout
        self.reservas = list(reservas)
        self.modelo_ativo = None                # último modelo que respondeu (pula os que falharam)
        self.messages = self                    # para funcionar como cliente.messages.create

    ESPERAS = (2, 5)            # segundos entre tentativas quando o provedor está sobrecarregado
    TEMPORARIOS = {429, 500, 502, 503, 504}

    def _post(self, corpo):
        """Envia o pedido. Erro temporário (sobrecarga, limite por minuto, rede) -> espera e tenta de novo."""
        dados = json.dumps(corpo).encode()
        ultimo = None
        for tentativa, espera in enumerate((0,) + self.ESPERAS):
            if espera:
                time.sleep(espera)
            req = urllib.request.Request(f"{self.url}/chat/completions", data=dados,
                                         headers={"Content-Type": "application/json",
                                                  "Authorization": f"Bearer {self.chave}"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                detalhe = e.read().decode(errors="replace")[:300]
                if e.code == 404:                       # modelo não existe para esta chave
                    raise ProvedorIndisponivel(f"modelo {corpo.get('model')} não encontrado") from e
                if e.code not in self.TEMPORARIOS:
                    raise RuntimeError(f"Erro {e.code} do provedor: {detalhe}") from e
                ultimo = e.code
            except (urllib.error.URLError, TimeoutError, OSError) as e:      # rede instável
                ultimo = type(e).__name__
        raise ProvedorIndisponivel(f"erro {ultimo} em {corpo.get('model')} depois de "
                                   f"{len(self.ESPERAS) + 1} tentativas")

    def create(self, model, max_tokens, messages, system="", tools=None, **_):
        corpo = _para_openai(system, messages, tools)
        corpo["max_tokens"] = max_tokens
        candidatos = [model] + [m for m in self.reservas if m != model]
        if self.modelo_ativo in candidatos:          # começa pelo que funcionou da última vez
            candidatos.remove(self.modelo_ativo)
            candidatos.insert(0, self.modelo_ativo)
        falhas = []
        for m in candidatos:
            try:
                resposta = self._post({**corpo, "model": m})
                self.modelo_ativo = m
                return _da_openai(resposta)
            except ProvedorIndisponivel as e:
                falhas.append(str(e))
        if any("429" in f for f in falhas):
            raise RuntimeError("Limite da cota grátis atingido em todos os modelos. Espere um minuto e "
                               "tente de novo, ou use outro provedor (veja provedores.py).")
        raise RuntimeError("Todos os modelos estão sobrecarregados agora (" + "; ".join(falhas) + "). "
                           "Tente de novo em alguns minutos, ou use o Groq: "
                           "export GROQ_API_KEY=... e export LLM_PROVEDOR=groq.")

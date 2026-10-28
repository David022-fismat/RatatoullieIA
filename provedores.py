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
import urllib.error
import urllib.request
from types import SimpleNamespace as NS

PROVEDORES = {
    # nome: (variável da chave, endereço da API, modelo padrão)
    "gemini": ("GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai",
               "gemini-3.8-flash"),
    "groq": ("GROQ_API_KEY", "https://api.groq.com/openai/v1", "openai/gpt-oss-120b"),
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
    return ClienteOpenAICompat(url, chave), os.getenv("MODELO_ORQUESTRADOR", modelo)


def funcao_texto(provedor):
    """Função prompt -> texto, para o Montador no modo LLM."""
    if provedor == "anthropic":
        from montador import llm_anthropic
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
            chamadas = [{"id": b["id"], "type": "function",
                         "function": {"name": b["name"], "arguments": json.dumps(b["input"], ensure_ascii=False)}}
                        for b in c if b["type"] == "tool_use"]
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
        blocos.append(NS(type="tool_use", id=c.get("id") or f"chamada_{i}", name=c["function"]["name"],
                         input=args))
    parou = "tool_use" if any(b.type == "tool_use" for b in blocos) else "end_turn"
    return NS(content=blocos or [NS(type="text", text="")], stop_reason=parou)


class ClienteOpenAICompat:
    def __init__(self, url, chave, timeout=60):
        self.url, self.chave, self.timeout = url.rstrip("/"), chave, timeout
        self.messages = self                    # para funcionar como cliente.messages.create

    def _post(self, corpo):
        req = urllib.request.Request(f"{self.url}/chat/completions", data=json.dumps(corpo).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Authorization": f"Bearer {self.chave}"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            detalhe = e.read().decode(errors="replace")[:300]
            if e.code == 429:
                raise RuntimeError("Limite da cota grátis atingido; espere um pouco e tente de novo.") from e
            raise RuntimeError(f"Erro {e.code} do provedor: {detalhe}") from e

    def create(self, model, max_tokens, messages, system="", tools=None, **_):
        corpo = _para_openai(system, messages, tools)
        corpo.update({"model": model, "max_tokens": max_tokens})
        return _da_openai(self._post(corpo))

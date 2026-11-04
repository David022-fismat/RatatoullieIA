"""
Orquestrador: agente com LLM que DECIDE quais agentes chamar, em que ordem e o que fazer com o resultado.

    python layout/agente_interativo.py --chat   # conversa com o Orquestrador (chave do Gemini, Groq ou Anthropic;
                                         # veja provedores.py)
    python demos/demo_orquestrador.py       # mesma coisa com um LLM simulado, para ver as decisões sem chave

Como funciona (padrão ReAct / tool calling):
  1. O Guardião lê a mensagem antes do LLM. Condição de saúde -> resposta fixa, o LLM nem é chamado.
  2. O LLM recebe a mensagem e a lista de FERRAMENTAS (os outros agentes) e escolhe uma.
  3. O Python executa a ferramenta e devolve o resultado ao LLM.
  4. O LLM olha o resultado e decide de novo: outra ferramenta, perguntar algo ou responder.
  5. Para quando o LLM responde em texto ou depois de MAX_PASSOS ferramentas.

O que o LLM NÃO pode fazer, por construção:
  - inventar receita ou nutriente: só existem as receitas que o Montador propõe e o Avaliador aprova;
  - remover restrição (vegetariano, celíaco...): não existe ferramenta para isso, só para adicionar;
  - furar os vetos do Avaliador: ele roda sempre, dentro de opcoes_de_refeicao.
Cada decisão fica registrada em logs/decisoes.jsonl (explicabilidade e auditoria).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from .agentes import (ARQ_PERFIL, RESTRICOES, Guardiao, LeitorDeNota, Perfil, carregar_base, reconhecer,
                      salvar_perfil)
from .avaliador import Avaliador
from .memoria import PESO_NOVIDADE, MemoriaSemana
from .montador import Montador
from .planejamento import aprender_com_feedback, planejar

RAIZ = Path(__file__).resolve().parent.parent      # pasta principal do projeto
ARQ_LOG = RAIZ / "logs" / "decisoes.jsonl"
MAX_PASSOS = 8
CARACTERISTICAS = ("natural", "tem_vegetal", "gosto", "rapidez", "novidade")

INSTRUCOES = """Você é o Orquestrador do RatatouilleIA, um assistente brasileiro de planejamento de refeições.
Você conversa com a pessoa e DECIDE quais ferramentas chamar. Cada ferramenta é um agente do sistema.
O sistema funciona por OPÇÕES: você oferece algumas refeições, a pessoa escolhe uma e o sistema aprende.

Regras:
- Receitas, quantidades e nutrientes só podem vir das ferramentas. Nunca invente nenhum deles.
- Restrições alimentares (vegetariano, celíaco etc.) são de segurança: você não pode removê-las nem
  sugerir algo que as viole. Se a pessoa pedir para remover, diga que ela precisa refazer o perfil.
- Para sugerir refeições, use opcoes_de_refeicao e apresente as opções NUMERADAS (1, 2, 3...), cada uma
  com uma frase sobre POR QUE ela entrou (use o campo "por_que").
- Se a pessoa escolher uma opção ("quero a 2", "vou fazer o virado"), chame escolher_receita com o nome
  EXATO da opção. Se ela pedir outras opções, chame opcoes_de_refeicao com outras_opcoes=true.
- Interprete pedidos vagos com bom senso ("sem tempo" = até 20 min) e diga como interpretou.
- Se vierem menos opções que o pedido, decida: tentar de novo com um limite de tempo maior ou perguntar.
- Se a pessoa contar um gosto ("não gosto de jiló", "amo frango"), use atualizar_preferencias.
- Responda em português, curto.
- O app mostra, abaixo da sua resposta, o modo de preparo e um link de vídeos do YouTube de cada opção:
  não copie o preparo inteiro nem invente links. Se a pessoa perguntar como fazer, use o campo "preparo".
- O Avaliador lembra o que a pessoa escolheu nos últimos 7 dias e tira pontos de receitas repetidas ou
  parecidas; se o "por_que" disser que uma receita perdeu pontos por repetição, mencione isso.
"""

FERRAMENTAS = [
    {"name": "ver_perfil",
     "description": "Mostra o perfil salvo (restrições, pessoas, tempo, gostos) e o que a pessoa escolheu na semana.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "atualizar_preferencias",
     "description": "Atualiza o perfil: gostos, número de pessoas, tempo máximo padrão ou NOVAS restrições. "
                    "Não remove restrições.",
     "input_schema": {"type": "object", "properties": {
         "gosta": {"type": "array", "items": {"type": "string"}},
         "nao_gosta": {"type": "array", "items": {"type": "string"}},
         "pessoas": {"type": "integer", "minimum": 1, "maximum": 12},
         "tempo_max_min": {"type": "integer", "minimum": 5, "maximum": 180},
         "adicionar_restricoes": {"type": "array", "items": {"type": "string", "enum": RESTRICOES}}}}},
    {"name": "opcoes_de_refeicao",
     "description": "Chama o Montador e o Avaliador para oferecer n opções de refeição diferentes entre si, "
                    "que respeitam o perfil. Cada opção volta com nota, motivo, ingredientes e nutrientes.",
     "input_schema": {"type": "object", "properties": {
         "n": {"type": "integer", "minimum": 1, "maximum": 8, "description": "quantas opções (padrão 4)"},
         "tempo_max_min_hoje": {"type": "integer", "minimum": 5, "maximum": 180,
                                "description": "limite de tempo só para este pedido (não muda o perfil)"},
         "outras_opcoes": {"type": "boolean",
                           "description": "true = não repetir nenhuma opção já mostrada nesta conversa"}}}},
    {"name": "escolher_receita",
     "description": "Registra a opção que a pessoa escolheu. O sistema aprende comparando a escolhida com as "
                    "outras opções mostradas junto, e passa a lembrar dela na semana.",
     "input_schema": {"type": "object", "properties": {
         "nome": {"type": "string", "description": "nome exato de uma das opções mostradas"}},
         "required": ["nome"]}},
]


class Orquestrador:
    def __init__(self, cliente=None, modelo=None, llm_montador=None, perfil=None, estoque=None,
                 salvar=True, memoria=None):
        self.ing, self.rec, restr = carregar_base()
        self.leitor = LeitorDeNota(self.ing)
        self.guardiao = Guardiao(restr)
        # memória da semana: o Avaliador lembra o que já sugeriu e evita repetir
        self.memoria = memoria if memoria is not None else MemoriaSemana(self.ing, salvar=salvar)
        self.avaliador = Avaliador(self.ing, restr, memoria=self.memoria)
        self.llm_montador = llm_montador          # função prompt -> texto, ou None (modo base)
        self.cliente = cliente
        self.modelo = modelo
        self.salvar = salvar
        self.perfil = perfil or self._carregar_perfil()
        self.estoque = dict(estoque or {})  # opcional: o fluxo principal é por opções, sem despensa
        self.ultimo_plano = []          # Resultados do Avaliador das últimas opções mostradas
        self.mostradas = set()          # nomes de todas as opções já mostradas (para "outras opções")
        self.historico = []             # mensagens da conversa (memória de curto prazo)
        self.preparos = {}              # nome -> modo de preparo das receitas sugeridas nesta mensagem
        self.decisoes = []              # decisões do último turno (para mostrar e auditar)

    # ------------------------------------------------------------------ persistência
    def _carregar_perfil(self):
        if ARQ_PERFIL.exists():
            return Perfil(**json.loads(ARQ_PERFIL.read_text(encoding="utf-8")))
        return Perfil()

    def _persistir(self):
        if self.salvar:
            salvar_perfil(self.perfil)

    def _log(self, registro):
        if self.salvar:
            ARQ_LOG.parent.mkdir(exist_ok=True)
            with open(ARQ_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), **registro},
                                   ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------ ferramentas
    def _nome(self, iid):
        return self.ing[iid]["nome"]

    def ver_perfil(self):
        p = self.perfil
        return {"restricoes": p.restricoes, "pessoas": p.pessoas, "tempo_max_min": p.tempo_max_min,
                "regiao": p.regiao, "gosta": [self._nome(i) for i in p.gosta if i in self.ing],
                "nao_gosta": [self._nome(i) for i in p.nao_gosta if i in self.ing],
                "escolhidas_nos_ultimos_7_dias": [e["nome"] for e in self.memoria.recentes()]}

    def _ids(self, nomes):
        ok, nao = [], []
        for n in nomes:
            iid, _ = reconhecer(n, self.leitor)
            (ok if iid else nao).append(iid or n)
        return ok, nao

    def atualizar_preferencias(self, gosta=(), nao_gosta=(), pessoas=None, tempo_max_min=None,
                               adicionar_restricoes=()):
        p, mudou = self.perfil, []
        g, g_nao = self._ids(gosta)
        ng, ng_nao = self._ids(nao_gosta)
        for i in g:
            if i not in p.gosta:
                p.gosta.append(i); mudou.append(f"gosta de {self._nome(i)}")
            if i in p.nao_gosta:
                p.nao_gosta.remove(i)
        for i in ng:
            if i not in p.nao_gosta:
                p.nao_gosta.append(i); mudou.append(f"não gosta de {self._nome(i)}")
            if i in p.gosta:
                p.gosta.remove(i)
        if pessoas:
            p.pessoas = int(pessoas); mudou.append(f"{p.pessoas} pessoa(s)")
        if tempo_max_min:
            p.tempo_max_min = int(tempo_max_min); mudou.append(f"até {p.tempo_max_min} min")
        for r in adicionar_restricoes:
            if r in RESTRICOES and r not in p.restricoes:
                p.restricoes.append(r); mudou.append(f"restrição {r}")
        self._persistir()
        return {"mudancas": mudou, "nao_existem_na_base": g_nao + ng_nao}

    def _receita_saida(self, x, numero):
        r = x.receita
        fator = self.perfil.pessoas / max(1, r["porcoes"])
        nut = x.detalhes["nutrientes_por_pessoa"]
        return {"numero": numero, "nome": r["nome"], "tempo_min": r["tempo_min"], "nota": x.nota,
                "por_que": x.explicacao,
                "ingredientes": {self._nome(i["id"]): round(i["gramas"] * fator) for i in r["ingredientes"]},
                "preparo": r.get("preparo", ""),
                "por_pessoa": {"kcal": nut["kcal"], "proteina_g": nut["proteina_g"], "fibra_g": nut["fibra_g"]}}

    def opcoes_de_refeicao(self, n=4, tempo_max_min_hoje=None, outras_opcoes=False):
        perfil = self.perfil
        if tempo_max_min_hoje:                      # cópia: o limite de hoje não muda o perfil salvo
            perfil = Perfil(**{**perfil.__dict__, "tempo_max_min": int(tempo_max_min_hoje),
                               "pesos": dict(perfil.pesos)})
        montador = Montador(self.ing, self.rec, self.guardiao, llm=self.llm_montador)
        evitar = self.mostradas if outras_opcoes else ()
        # pede o dobro ao laço Montador ↔ Avaliador para ter de onde escolher opções variadas
        res = planejar(montador, self.avaliador, perfil, self.estoque, n=2 * int(n), evitar=evitar)
        # opções diferentes entre si: uma por proteína principal antes de repetir (ordem da nota)
        chave = {id(x): montador._proteina_principal({i["id"]: i["gramas"] for i in x.receita["ingredientes"]})
                 for x in res["cardapio"]}
        opcoes = montador._variadas([(x.nota, x, chave[id(x)]) for x in res["cardapio"]], int(n))
        self.ultimo_plano = opcoes
        self.mostradas.update(x.receita["nome"] for x in opcoes)
        self.preparos.update({x.receita["nome"]: x.receita.get("preparo", "") for x in opcoes})
        return {"pedidas": int(n), "encontradas": len(opcoes),
                "limite_de_tempo_usado": perfil.tempo_max_min,
                "rodadas_montador_avaliador": len(res["historico"]),
                "motivos_de_rejeicao": sorted({m for h in res["historico"] for m in h["motivos"]}),
                "opcoes": [self._receita_saida(x, k) for k, x in enumerate(opcoes, start=1)]}

    def escolher_receita(self, nome):
        """A pessoa escolheu uma das opções: aprende com o CONTRASTE entre a escolhida e as outras
        mostradas junto, e registra só a escolhida na memória da semana."""
        por_nome = {x.receita["nome"]: x for x in self.ultimo_plano}
        if nome not in por_nome:
            return {"erro": "essa não está entre as últimas opções; nomes válidos: " + ", ".join(por_nome)}
        caracts = {n: {k: x.detalhes[k] for k in CARACTERISTICAS if k in x.detalhes}
                   for n, x in por_nome.items()}
        comuns = set.intersection(*(set(c) for c in caracts.values()))
        caracts = {n: {k: v for k, v in c.items() if k in comuns} for n, c in caracts.items()}
        antes = {"novidade": PESO_NOVIDADE, **self.perfil.pesos}
        if len(caracts) > 1:                        # com 1 opção só, não há contraste para aprender
            aprender_com_feedback(self.perfil, caracts, [nome])
        self.memoria.registrar([por_nome[nome].receita])        # o Avaliador vai lembrar
        self._persistir()
        return {"escolhida": nome, "preparo": por_nome[nome].receita.get("preparo", ""),
                "pesos_que_mudaram": {k: [round(antes.get(k, 1.0), 2), round(v, 2)]
                                      for k, v in self.perfil.pesos.items()
                                      if abs(v - antes.get(k, 1.0)) > 0.005}}

    def executar(self, nome, argumentos):
        """Ponte entre a decisão do LLM e o código. Erros voltam para o LLM decidir o que fazer."""
        if nome not in {f["name"] for f in FERRAMENTAS}:
            return {"erro": f"ferramenta inexistente: {nome}"}
        try:
            return getattr(self, nome)(**argumentos)
        except Exception as e:                    # argumento errado etc.
            return {"erro": f"{type(e).__name__}: {e}"}

    # ------------------------------------------------------------------ o laço de decisão
    def _contexto(self):
        p = self.ver_perfil()
        return (f"\n\nEstado atual (já carregado, não precisa chamar ver_perfil para isto): "
                f"{json.dumps(p, ensure_ascii=False)}")

    def responder(self, mensagem):
        self.decisoes, self.preparos = [], {}
        aviso = self.guardiao.checar_mensagem(mensagem)          # o Guardião fala antes do LLM
        if aviso:
            self.decisoes.append({"passo": 0, "decisao": "Guardião bloqueou (condição de saúde)"})
            self._log({"mensagem": mensagem, "decisoes": self.decisoes, "resposta": aviso})
            return aviso
        if self.cliente is None:
            from .provedores import criar_cliente, provedor_disponivel
            self.cliente, self.modelo = criar_cliente(provedor_disponivel() or "anthropic")

        self.historico.append({"role": "user", "content": mensagem})
        resposta = None
        for passo in range(1, MAX_PASSOS + 1):
            resp = self.cliente.messages.create(model=self.modelo, max_tokens=1500,
                                                system=INSTRUCOES + self._contexto(),
                                                tools=FERRAMENTAS, messages=self.historico)
            blocos = [_bloco_para_dict(b) for b in resp.content]
            self.historico.append({"role": "assistant", "content": blocos})
            chamadas = [b for b in blocos if b["type"] == "tool_use"]
            if not chamadas:                                      # decidiu responder
                resposta = "".join(b["text"] for b in blocos if b["type"] == "text").strip()
                break
            resultados = []
            for c in chamadas:
                saida = self.executar(c["name"], c["input"])
                self.decisoes.append({"passo": passo, "ferramenta": c["name"], "argumentos": c["input"],
                                      "resultado": _resumo(c["name"], saida)})
                resultados.append({"type": "tool_result", "tool_use_id": c["id"],
                                   "content": json.dumps(saida, ensure_ascii=False)})
            self.historico.append({"role": "user", "content": resultados})
        if resposta is None:
            resposta = ("Precisei de passos demais para decidir. Pode reformular o pedido "
                        "de um jeito mais específico?")
            self.historico.append({"role": "assistant", "content": resposta})
        self._log({"mensagem": mensagem, "decisoes": self.decisoes, "resposta": resposta})
        return resposta


def _bloco_para_dict(b):
    if isinstance(b, dict):
        return b
    if b.type == "tool_use":
        d = {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
        if getattr(b, "extra_content", None):     # só vem do Gemini/Groq; a Anthropic não usa
            d["extra_content"] = b.extra_content
        return d
    return {"type": "text", "text": getattr(b, "text", "")}


def _resumo(nome, saida):
    if "erro" in saida:
        return "erro: " + saida["erro"]
    if nome == "opcoes_de_refeicao":
        return f"{saida['encontradas']} de {saida['pedidas']} opções (até {saida['limite_de_tempo_usado']} min)"
    if nome == "escolher_receita":
        return f"escolheu {saida['escolhida']}; pesos: {saida['pesos_que_mudaram']}"
    if nome == "atualizar_preferencias":
        return ", ".join(saida["mudancas"]) or "nada mudou"
    return "ok"


def mostrar_decisoes(decisoes):
    for d in decisoes:
        if "ferramenta" in d:
            args = ", ".join(f"{k}={v}" for k, v in d["argumentos"].items())
            print(f"   [decisão {d['passo']}] {d['ferramenta']}({args}) -> {d['resultado']}")
        else:
            print(f"   [decisão] {d['decisao']}")


def conversar(orq, mostrar=True):
    print("RatatouilleIA. Escreva o que precisa (ex.: 'tô sem tempo, o que faço hoje?').")
    print("Comandos: /decisoes liga/desliga o rastro de decisões, /sair encerra.\n")
    while True:
        try:
            msg = input("você> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not msg:
            continue
        if msg in ("/sair", "sair"):
            break
        if msg == "/decisoes":
            mostrar = not mostrar
            print(f"   rastro de decisões {'ligado' if mostrar else 'desligado'}")
            continue
        resposta = orq.responder(msg)
        if mostrar:
            mostrar_decisoes(orq.decisoes)
        print(f"\nagente> {resposta}\n")

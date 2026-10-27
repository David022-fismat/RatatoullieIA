"""
Orquestrador: agente com LLM que DECIDE quais agentes chamar, em que ordem e o que fazer com o resultado.

    python agente_interativo.py --chat           # conversa com o Orquestrador (precisa de ANTHROPIC_API_KEY)
    python demo_orquestrador.py       # mesma coisa com um LLM simulado, para ver as decisões sem chave

Como funciona (padrão ReAct / tool calling):
  1. O Guardião lê a mensagem antes do LLM. Condição de saúde -> resposta fixa, o LLM nem é chamado.
  2. O LLM recebe a mensagem e a lista de FERRAMENTAS (os outros agentes) e escolhe uma.
  3. O Python executa a ferramenta e devolve o resultado ao LLM.
  4. O LLM olha o resultado e decide de novo: outra ferramenta, perguntar algo ou responder.
  5. Para quando o LLM responde em texto ou depois de MAX_PASSOS ferramentas.

O que o LLM NÃO pode fazer, por construção:
  - inventar receita ou nutriente: só existem as receitas que o Montador propõe e o Avaliador aprova;
  - remover restrição (vegetariano, celíaco...): não existe ferramenta para isso, só para adicionar;
  - furar os vetos do Avaliador: ele roda sempre, dentro de planejar_refeicoes.
Cada decisão fica registrada em logs/decisoes.jsonl (explicabilidade e auditoria).
"""
from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path

from agente_interativo import ARQ_PERFIL, RESTRICOES, reconhecer, salvar_perfil
from agentes import Comprador, Estado, Guardiao, LeitorDeNota, Perfil, Planejador, carregar_base
from avaliador import Avaliador
from montador import Montador, llm_anthropic
from planejamento import aprender_com_feedback, planejar

RAIZ = Path(__file__).parent
ARQ_ESTOQUE = RAIZ / "estoque.json"
ARQ_LOG = RAIZ / "logs" / "decisoes.jsonl"
MAX_PASSOS = 8
CARACTERISTICAS = ("natural", "tem_vegetal", "gosto", "rapidez", "usa_estoque", "tem_em_casa")

INSTRUCOES = """Você é o Orquestrador do RatatouilleIA, um assistente brasileiro de planejamento de refeições.
Você conversa com a pessoa e DECIDE quais ferramentas chamar. Cada ferramenta é um agente do sistema.

Regras:
- Receitas, quantidades, nutrientes e preços só podem vir das ferramentas. Nunca invente nenhum deles.
- Restrições alimentares (vegetariano, celíaco etc.) são de segurança: você não pode removê-las nem
  sugerir algo que as viole. Se a pessoa pedir para remover, diga que ela precisa refazer o perfil.
- Se a pessoa contar o que comprou ou o que tem, atualize o estoque antes de planejar.
- Interprete pedidos vagos com bom senso ("sem tempo" = até 20 min; "pra hoje" = 1 refeição;
  "a semana" = 5 a 7 refeições) e diga na resposta como você interpretou.
- Se um plano vier incompleto, decida: tentar de novo com um limite de tempo maior, oferecer só o que
  dá com o que tem em casa, ou perguntar à pessoa. Explique a escolha.
- Se a pessoa falar de orçamento ou de quanto pode gastar, use planejar_com_orcamento.
- Se a pessoa disser o que fez ou não fez, registre o retorno para o sistema aprender.
- Ingrediente que a ferramenta não reconhecer: avise a pessoa, não invente um equivalente.
- Responda em português, curto, explicando POR QUE cada receita foi escolhida (use o campo "por_que").
"""

FERRAMENTAS = [
    {"name": "ver_perfil_e_estoque",
     "description": "Mostra o perfil salvo (restrições, pessoas, tempo, gostos) e o estoque atual da casa.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "atualizar_estoque",
     "description": "Adiciona ou remove ingredientes do estoque. Use quando a pessoa disser o que comprou, "
                    "o que tem ou o que acabou. Devolve o que foi reconhecido e o que não existe na base.",
     "input_schema": {"type": "object", "properties": {
         "adicionar": {"type": "array", "description": "ingredientes que a pessoa tem",
                       "items": {"type": "object", "properties": {
                           "nome": {"type": "string"},
                           "gramas": {"type": "number", "description": "omita se a pessoa não disse"}},
                           "required": ["nome"]}},
         "remover": {"type": "array", "items": {"type": "string"}, "description": "ingredientes que acabaram"}}}},
    {"name": "atualizar_preferencias",
     "description": "Atualiza o perfil: gostos, número de pessoas, tempo máximo padrão ou NOVAS restrições. "
                    "Não remove restrições.",
     "input_schema": {"type": "object", "properties": {
         "gosta": {"type": "array", "items": {"type": "string"}},
         "nao_gosta": {"type": "array", "items": {"type": "string"}},
         "pessoas": {"type": "integer", "minimum": 1, "maximum": 12},
         "tempo_max_min": {"type": "integer", "minimum": 5, "maximum": 180},
         "adicionar_restricoes": {"type": "array", "items": {"type": "string", "enum": RESTRICOES}}}}},
    {"name": "planejar_refeicoes",
     "description": "Chama o Montador e o Avaliador para montar n refeições que respeitam o perfil. "
                    "Cada receita volta com nota, motivo da escolha, o que falta comprar e nutrientes.",
     "input_schema": {"type": "object", "properties": {
         "n": {"type": "integer", "minimum": 1, "maximum": 14},
         "tempo_max_min_hoje": {"type": "integer", "minimum": 5, "maximum": 180,
                                "description": "limite de tempo só para este pedido (não muda o perfil)"},
         "so_com_o_que_tem": {"type": "boolean",
                              "description": "true = só receitas que não exigem comprar nada"}},
         "required": ["n"]}},
    {"name": "lista_de_compras",
     "description": "Junta o que falta comprar para as receitas escolhidas do último plano, com custo estimado.",
     "input_schema": {"type": "object", "properties": {
         "receitas": {"type": "array", "items": {"type": "string"},
                      "description": "nomes das receitas do último plano; vazio = todas"}}}},
    {"name": "planejar_com_orcamento",
     "description": "Chama o Comprador (otimização com PuLP): escolhe refeições e a lista de compras que "
                    "cabem no orçamento, aproveitando o estoque.",
     "input_schema": {"type": "object", "properties": {
         "orcamento_reais": {"type": "number", "minimum": 1},
         "refeicoes": {"type": "integer", "minimum": 1, "maximum": 14}},
         "required": ["orcamento_reais", "refeicoes"]}},
    {"name": "registrar_retorno",
     "description": "Registra quais receitas sugeridas nesta conversa a pessoa fez ou faria. O sistema ajusta os pesos "
                    "do perfil para as próximas sugestões.",
     "input_schema": {"type": "object", "properties": {
         "feitas": {"type": "array", "items": {"type": "string"}}}, "required": ["feitas"]}},
]


class Orquestrador:
    def __init__(self, cliente=None, modelo=None, montador_com_llm=False, perfil=None, estoque=None,
                 salvar=True):
        self.ing, self.rec, restr = carregar_base()
        self.leitor = LeitorDeNota(self.ing)
        self.guardiao = Guardiao(restr)
        self.avaliador = Avaliador(self.ing, restr)
        self.montador_com_llm = montador_com_llm
        self.comprador = Comprador(self.ing, Planejador(self.ing, self.rec, self.guardiao))
        self.cliente = cliente
        self.modelo = modelo or os.getenv("MODELO_ORQUESTRADOR", "claude-haiku-5-5")
        self.salvar = salvar
        self.perfil = perfil or self._carregar_perfil()
        self.estoque = estoque if estoque is not None else self._carregar_estoque()
        self.ultimo_plano = []          # Resultados do Avaliador do último planejar_refeicoes
        self.sugeridas = {}             # tudo o que foi sugerido na conversa: nome -> Resultado
        self.historico = []             # mensagens da conversa (memória de curto prazo)
        self.decisoes = []              # decisões do último turno (para mostrar e auditar)

    # ------------------------------------------------------------------ persistência
    def _carregar_perfil(self):
        if ARQ_PERFIL.exists():
            return Perfil(**json.loads(ARQ_PERFIL.read_text(encoding="utf-8")))
        return Perfil()

    def _carregar_estoque(self):
        if ARQ_ESTOQUE.exists():
            return json.loads(ARQ_ESTOQUE.read_text(encoding="utf-8"))
        return {}

    def _persistir(self):
        if self.salvar:
            salvar_perfil(self.perfil)
            ARQ_ESTOQUE.write_text(json.dumps(self.estoque, ensure_ascii=False, indent=1), encoding="utf-8")

    def _log(self, registro):
        if self.salvar:
            ARQ_LOG.parent.mkdir(exist_ok=True)
            with open(ARQ_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": time.strftime("%Y-%m-%d %H:%M:%S"), **registro},
                                   ensure_ascii=False) + "\n")

    # ------------------------------------------------------------------ ferramentas
    def _nome(self, iid):
        return self.ing[iid]["nome"]

    def ver_perfil_e_estoque(self):
        p = self.perfil
        return {"restricoes": p.restricoes, "pessoas": p.pessoas, "tempo_max_min": p.tempo_max_min,
                "regiao": p.regiao, "gosta": [self._nome(i) for i in p.gosta if i in self.ing],
                "nao_gosta": [self._nome(i) for i in p.nao_gosta if i in self.ing],
                "estoque": {self._nome(i): g for i, g in self.estoque.items() if i in self.ing}}

    def _ids(self, nomes):
        ok, nao = [], []
        for n in nomes:
            iid, _ = reconhecer(n, self.leitor)
            (ok if iid else nao).append(iid or n)
        return ok, nao

    def atualizar_estoque(self, adicionar=(), remover=()):
        reconhecidos, desconhecidos = [], []
        for item in adicionar:
            iid, _ = reconhecer(item["nome"], self.leitor)
            if not iid:
                desconhecidos.append(item["nome"])
                continue
            g = float(item.get("gramas") or self.ing[iid]["embalagem_g"])   # sem quantidade: 1 embalagem
            self.estoque[iid] = self.estoque.get(iid, 0) + g
            reconhecidos.append(f"{self._nome(iid)} ({g:.0f} g)")
        removidos, _ = self._ids(remover)
        for iid in removidos:
            self.estoque.pop(iid, None)
        self._persistir()
        return {"adicionados": reconhecidos, "removidos": [self._nome(i) for i in removidos],
                "nao_existem_na_base": desconhecidos}

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

    def _receita_saida(self, x):
        r = x.receita
        fator = self.perfil.pessoas / max(1, r["porcoes"])
        falta = [self._nome(i["id"]) for i in r["ingredientes"]
                 if self.estoque.get(i["id"], 0) < i["gramas"] * fator]
        nut = x.detalhes["nutrientes_por_pessoa"]
        return {"nome": r["nome"], "tempo_min": r["tempo_min"], "nota": x.nota, "por_que": x.explicacao,
                "ingredientes": {self._nome(i["id"]): round(i["gramas"] * fator) for i in r["ingredientes"]},
                "falta_comprar": falta,
                "por_pessoa": {"kcal": nut["kcal"], "proteina_g": nut["proteina_g"], "fibra_g": nut["fibra_g"]}}

    def planejar_refeicoes(self, n, tempo_max_min_hoje=None, so_com_o_que_tem=False):
        perfil = self.perfil
        if tempo_max_min_hoje:                      # cópia: o limite de hoje não muda o perfil salvo
            perfil = Perfil(**{**perfil.__dict__, "tempo_max_min": int(tempo_max_min_hoje),
                               "pesos": dict(perfil.pesos)})
        montador = Montador(self.ing, self.rec, self.guardiao,
                            llm=llm_anthropic if self.montador_com_llm else None)
        pedir = n * 4 if so_com_o_que_tem else n
        res = planejar(montador, self.avaliador, perfil, self.estoque, n=pedir)
        cardapio = res["cardapio"]
        if so_com_o_que_tem:
            cardapio = [x for x in cardapio if not self._receita_saida(x)["falta_comprar"]]
        cardapio = cardapio[:n]
        self.ultimo_plano = cardapio
        self.sugeridas.update({x.receita["nome"]: x for x in cardapio})
        return {"pedidas": n, "encontradas": len(cardapio),
                "limite_de_tempo_usado": perfil.tempo_max_min,
                "rodadas_montador_avaliador": len(res["historico"]),
                "motivos_de_rejeicao": sorted({m for h in res["historico"] for m in h["motivos"]}),
                "receitas": [self._receita_saida(x) for x in cardapio]}

    def lista_de_compras(self, receitas=()):
        escolhidas = [x for x in self.ultimo_plano if not receitas or x.receita["nome"] in receitas]
        if not escolhidas:
            return {"erro": "nenhuma receita do último plano com esses nomes; planeje antes"}
        precisa = {}
        for x in escolhidas:
            fator = self.perfil.pessoas / max(1, x.receita["porcoes"])
            for i in x.receita["ingredientes"]:
                precisa[i["id"]] = precisa.get(i["id"], 0) + i["gramas"] * fator
        itens, total = [], 0.0
        for iid, g in precisa.items():
            falta = g - self.estoque.get(iid, 0)
            if falta > 0:
                emb = math.ceil(falta / self.ing[iid]["embalagem_g"])
                custo = emb * self.ing[iid]["preco_embalagem"]
                total += custo
                itens.append({"item": self._nome(iid), "embalagens": emb,
                              "embalagem_g": self.ing[iid]["embalagem_g"], "custo_estimado": round(custo, 2)})
        return {"itens": itens, "total_estimado_reais": round(total, 2),
                "aviso": "preços estimados pelo grupo; confira no mercado"}

    def planejar_com_orcamento(self, orcamento_reais, refeicoes):
        estado = Estado(perfil=self.perfil, estoque=dict(self.estoque))
        res = self.comprador.resolver(estado, float(orcamento_reais), int(refeicoes))
        if res is None:
            return {"cabe_no_orcamento": False,
                    "sugestao": "diminuir o número de refeições ou aumentar o orçamento"}
        return {"cabe_no_orcamento": True, "total_reais": round(res["total"], 2),
                "refeicoes": [{"receita": self.rec[k]["nome"], "vezes": n} for k, n in res["semana"]],
                "comprar": [{"item": self._nome(i), "embalagens": n,
                             "custo": round(n * self.ing[i]["preco_embalagem"], 2)} for i, n in res["lista"]],
                "aviso": "preços estimados pelo grupo; confira no mercado"}

    def registrar_retorno(self, feitas):
        if not self.sugeridas:
            return {"erro": "não há sugestões nesta conversa para avaliar"}
        # compara com TUDO o que foi sugerido na conversa (com 1 sugestão só, não haveria contraste)
        caracts = {nome: {k: x.detalhes[k] for k in CARACTERISTICAS} for nome, x in self.sugeridas.items()}
        validas = [f for f in feitas if f in caracts]
        antes = dict(self.perfil.pesos)
        aprender_com_feedback(self.perfil, caracts, validas)
        self._persistir()
        return {"registradas": validas, "ignoradas": [f for f in feitas if f not in caracts],
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
        p = self.ver_perfil_e_estoque()
        return (f"\n\nEstado atual (já carregado, não precisa chamar ver_perfil_e_estoque para isto): "
                f"{json.dumps(p, ensure_ascii=False)}")

    def responder(self, mensagem):
        self.decisoes = []
        aviso = self.guardiao.checar_mensagem(mensagem)          # o Guardião fala antes do LLM
        if aviso:
            self.decisoes.append({"passo": 0, "decisao": "Guardião bloqueou (condição de saúde)"})
            self._log({"mensagem": mensagem, "decisoes": self.decisoes, "resposta": aviso})
            return aviso
        if self.cliente is None:
            import anthropic
            self.cliente = anthropic.Anthropic()

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
        return {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
    return {"type": "text", "text": getattr(b, "text", "")}


def _resumo(nome, saida):
    if "erro" in saida:
        return "erro: " + saida["erro"]
    if nome == "planejar_refeicoes":
        return f"{saida['encontradas']} de {saida['pedidas']} receitas (até {saida['limite_de_tempo_usado']} min)"
    if nome == "atualizar_estoque":
        extra = f"; não existem: {', '.join(saida['nao_existem_na_base'])}" if saida["nao_existem_na_base"] else ""
        return f"+{len(saida['adicionados'])} itens{extra}"
    if nome == "lista_de_compras":
        return f"{len(saida['itens'])} itens, ~R$ {saida['total_estimado_reais']:.2f}"
    if nome == "planejar_com_orcamento":
        return f"R$ {saida['total_reais']:.2f}" if saida["cabe_no_orcamento"] else "não cabe no orçamento"
    if nome == "registrar_retorno":
        return f"pesos: {saida['pesos_que_mudaram']}"
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
    print("RatatouilleIA. Escreva o que precisa (ex.: 'comprei frango e tomate, o que faço hoje?').")
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

"""
Protótipo do agente de nutrição (Challenge 2).

Cada agente é uma função/classe simples. Nenhum deles depende de LLM para DECIDIR:
  - LeitorDeNota   -> percepção  (aqui: busca por sinônimos; depois: rede neural)
  - Guardiao       -> regras fixas de segurança (agente reativo simples)
  - Planejador     -> agente baseado em utilidade (nota ponderada por receita)
  - Comprador      -> agente baseado em objetivo + utilidade (programação linear inteira)
  - Orquestrador   -> recebe o pedido, chama os outros e monta a explicação
                      (é aqui que o LLM entra, só para conversar e explicar)

Todos leem e escrevem no mesmo "quadro" (o dicionário Estado), como o blackboard do Jan et al.
"""
from __future__ import annotations

import csv
import difflib
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

import pulp

KB = Path(__file__).parent / "kb"


# ----------------------------------------------------------------------------
# Base de conhecimento (parte estruturada): só leitura de CSV
# ----------------------------------------------------------------------------
def _ler(nome):
    with open(KB / nome, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def carregar_base():
    ingredientes = {r["id"]: r for r in _ler("ingredientes.csv")}
    for r in ingredientes.values():
        r["dias_validade"] = int(r["dias_validade"])
        r["embalagem_g"] = float(r["embalagem_g"])
        r["preco_embalagem"] = float(r["preco_embalagem"])
        r["sinonimos"] = r["sinonimos"].split("|")

    receitas = {r["id"]: r for r in _ler("receitas.csv")}
    for r in receitas.values():
        r["tempo_min"] = int(r["tempo_min"])
        r["refeicao"] = r["refeicao"].split("|")
        r["tags"] = [t for t in r["tags"].split("|") if t]
        r["itens"] = {}  # ingrediente -> gramas
    for linha in _ler("receita_ingrediente.csv"):
        receitas[linha["receita"]]["itens"][linha["ingrediente"]] = float(linha["gramas"])

    restricoes = {r["restricao"]: set(r["ingredientes_excluidos"].split("|"))
                  for r in _ler("restricoes.csv")}
    return ingredientes, receitas, restricoes


# ----------------------------------------------------------------------------
# Perfil e estado compartilhado
# ----------------------------------------------------------------------------
@dataclass
class Perfil:
    restricoes: list[str] = field(default_factory=list)      # regras rígidas
    regiao: str = "Brasil"
    tempo_max_min: int = 45
    pessoas: int = 2
    gosta: list[str] = field(default_factory=list)            # ingredientes favoritos
    nao_gosta: list[str] = field(default_factory=list)
    # pesos da nota (vêm do cadastro e são ajustados pelo feedback)
    pesos: dict = field(default_factory=lambda: {
        "gosto": 1.0, "rapidez": 1.0, "usa_estoque": 1.0,
        "natural": 1.0, "regiao": 0.5,
    })


@dataclass
class Estado:
    """O 'quadro compartilhado': todos os agentes leem e escrevem aqui."""
    perfil: Perfil
    estoque: dict = field(default_factory=dict)   # ingrediente -> gramas em casa
    eventos: list = field(default_factory=list)   # log para explicabilidade/auditoria

    def registrar(self, agente, msg):
        self.eventos.append(f"[{agente}] {msg}")


def _norm(txt):
    txt = unicodedata.normalize("NFKD", txt.lower())
    return "".join(c for c in txt if not unicodedata.combining(c)).strip()


# ----------------------------------------------------------------------------
# 1. Leitor de nota  (percepção)
# ----------------------------------------------------------------------------
class LeitorDeNota:
    """Transforma linhas abreviadas da NFC-e em ingredientes conhecidos.

    Versão atual: compara com nomes e sinônimos (difflib).
    Versão final: troque `classificar` por uma rede neural treinada
    (ex.: CNN 1D de caracteres) que devolve (ingrediente, confiança).
    O resto do sistema não muda, porque a interface é a mesma.
    """

    LIMIAR = 0.6  # abaixo disso o agente pergunta em vez de assumir

    def __init__(self, ingredientes):
        self.vocab = {}
        for iid, ing in ingredientes.items():
            for nome in [ing["nome"], *ing["sinonimos"]]:
                self.vocab[_norm(nome)] = iid

    def classificar(self, linha: str):
        texto = _norm(linha)
        melhor, conf = None, 0.0
        for nome, iid in self.vocab.items():
            s = difflib.SequenceMatcher(None, texto, nome).ratio()
            if nome in texto:          # nome inteiro aparece na linha
                s = max(s, 0.9)
            if s > conf:
                melhor, conf = iid, s
        return melhor, conf

    def ler(self, estado: Estado, nota: list[tuple[str, float]]):
        """nota = [(descricao_da_linha, gramas), ...]"""
        duvidas = []
        for linha, gramas in nota:
            iid, conf = self.classificar(linha)
            if iid and conf >= self.LIMIAR:
                estado.estoque[iid] = estado.estoque.get(iid, 0) + gramas
                estado.registrar("Leitor", f"'{linha}' -> {iid} ({conf:.0%})")
            else:
                duvidas.append(linha)
                estado.registrar("Leitor", f"'{linha}' não reconhecido; perguntar ao usuário")
        return duvidas


# ----------------------------------------------------------------------------
# 2. Guardião  (regras fixas: sempre a mesma resposta para o mesmo caso)
# ----------------------------------------------------------------------------
class Guardiao:
    CONDICOES_ENCAMINHAR = [
        "renal", "rim", "diabet", "gestante", "gravida", "cancer", "oncolog",
        "anorexia", "bulimia", "jejum", "emagrecer rapido", "cirurgia",
    ]

    def __init__(self, restricoes):
        self.restricoes = restricoes

    def proibidos(self, perfil: Perfil) -> set:
        out = set()
        for r in perfil.restricoes:
            out |= self.restricoes.get(r, set())
        return out

    def receita_permitida(self, receita, perfil: Perfil) -> bool:
        return not (set(receita["itens"]) & self.proibidos(perfil))

    def checar_mensagem(self, texto: str):
        t = _norm(texto)
        for c in self.CONDICOES_ENCAMINHAR:
            if c in t:
                return ("Para essa condição eu não monto plano: o certo é um "
                        "nutricionista ou médico acompanhar. Posso ajudar com "
                        "orientações gerais do Guia Alimentar, se quiser.")
        return None


# ----------------------------------------------------------------------------
# 3. Planejador  (agente baseado em utilidade)
# ----------------------------------------------------------------------------
class Planejador:
    def __init__(self, ingredientes, receitas, guardiao):
        self.ing, self.rec, self.guardiao = ingredientes, receitas, guardiao

    def caracteristicas(self, r, estado: Estado) -> dict:
        """Cada característica vai de 0 a 1. A nota é a soma ponderada delas."""
        p, itens = estado.perfil, r["itens"]
        total = sum(itens.values())
        gosto = (sum(1 for i in itens if i in p.gosta)
                 - sum(1 for i in itens if i in p.nao_gosta))
        # usa primeiro o que estraga rápido: peso maior para perecíveis em estoque
        usa = sum(min(g, estado.estoque.get(i, 0)) / (1 + self.ing[i]["dias_validade"] / 7)
                  for i, g in itens.items()) / total
        natural = sum(g for i, g in itens.items()
                      if self.ing[i]["nova"] == "in natura") / total
        return {
            "gosto": max(-1.0, min(1.0, gosto / 2)),
            "rapidez": 1 - min(r["tempo_min"], 60) / 60,
            "usa_estoque": min(1.0, usa * 2),
            "natural": natural,
            "regiao": 1.0 if r["regiao"] == p.regiao else 0.0,
        }

    def nota(self, r, estado):
        c = self.caracteristicas(r, estado)
        return sum(estado.perfil.pesos[k] * v for k, v in c.items()), c

    def candidatas(self, estado: Estado):
        """Filtro rígido (Guardião + tempo) e depois ranking por nota."""
        p, out = estado.perfil, []
        for r in self.rec.values():
            if not self.guardiao.receita_permitida(r, p):
                continue
            if r["tempo_min"] > p.tempo_max_min:
                continue
            n, c = self.nota(r, estado)
            out.append((n, r, c))
        return sorted(out, key=lambda t: -t[0])

    def explicar(self, c: dict, pesos: dict) -> str:
        contrib = sorted(((pesos[k] * v, k) for k, v in c.items()), reverse=True)
        frases = {"gosto": "tem ingredientes de que você gosta",
                  "rapidez": "é rápida", "usa_estoque": "usa o que já tem e estraga logo",
                  "natural": "é baseada em comida in natura", "regiao": "é da sua região"}
        return ", ".join(frases[k] for v, k in contrib[:2] if v > 0.2) or "equilibra os critérios"


# ----------------------------------------------------------------------------
# 4. Comprador  (objetivo: caber no orçamento; utilidade: melhor semana possível)
# ----------------------------------------------------------------------------
class Comprador:
    """Programação linear inteira com PuLP.

    Variáveis:
      x[r]   = quantas vezes a receita r entra na semana (0, 1 ou 2)
      emb[i] = quantas embalagens do ingrediente i comprar
    Restrições:
      sum x[r] = número de refeições
      emb[i]*tamanho_i + estoque_i >= gramas necessárias de i
      custo total <= orçamento
    Objetivo:
      maximizar soma(nota[r]*x[r]) - lambda * custo
    """

    def __init__(self, ingredientes, planejador):
        self.ing, self.plan = ingredientes, planejador

    def resolver(self, estado: Estado, orcamento: float, refeicoes: int, lam=0.02):
        cands = self.plan.candidatas(estado)
        if not cands:
            return None
        fator = estado.perfil.pessoas / 2  # receitas da base servem 2 pessoas
        prob = pulp.LpProblem("compras", pulp.LpMaximize)
        x = {r["id"]: pulp.LpVariable(f"x_{r['id']}", 0, 2, cat="Integer") for _, r, _ in cands}
        usados = {i for _, r, _ in cands for i in r["itens"]}
        emb = {i: pulp.LpVariable(f"emb_{i}", 0, cat="Integer") for i in usados}

        custo = pulp.lpSum(emb[i] * self.ing[i]["preco_embalagem"] for i in usados)
        nota = {r["id"]: n for n, r, _ in cands}
        prob += pulp.lpSum(nota[k] * x[k] for k in x) - lam * custo
        prob += pulp.lpSum(x.values()) == refeicoes
        prob += custo <= orcamento
        for i in usados:
            precisa = pulp.lpSum(r["itens"].get(i, 0) * fator * x[r["id"]] for _, r, _ in cands)
            prob += emb[i] * self.ing[i]["embalagem_g"] + estado.estoque.get(i, 0) >= precisa

        prob.solve(pulp.PULP_CBC_CMD(msg=False))
        if pulp.LpStatus[prob.status] != "Optimal":
            estado.registrar("Comprador", "orçamento insuficiente para as refeições pedidas")
            return None

        semana = [(k, int(v.value())) for k, v in x.items() if v.value() > 0.5]
        lista = [(i, int(v.value())) for i, v in emb.items() if v.value() > 0.5]
        total = sum(n * self.ing[i]["preco_embalagem"] for i, n in lista)
        estado.registrar("Comprador", f"lista de R$ {total:.2f} para {refeicoes} refeições")
        return {"semana": semana, "lista": lista, "total": total}


# ----------------------------------------------------------------------------
# 5. Aprendizado com o uso (ajuste simples dos pesos)
# ----------------------------------------------------------------------------
def aprender(estado: Estado, planejador: Planejador, receita, fez: bool, taxa=0.1):
    """Se fez a receita, reforça o que ela tinha de forte; se não fez, enfraquece."""
    c = planejador.caracteristicas(receita, estado)
    sinal = 1 if fez else -1
    for k, v in c.items():
        estado.perfil.pesos[k] = max(0.0, estado.perfil.pesos[k] + taxa * sinal * v)
    estado.registrar("Aprendizado", f"pesos -> { {k: round(v, 2) for k, v in estado.perfil.pesos.items()} }")


# ----------------------------------------------------------------------------
# 6. Orquestrador
# ----------------------------------------------------------------------------
class Orquestrador:
    """Decide qual agente chamar e monta a resposta.

    Aqui a intenção é detectada por palavras-chave. Na versão final, um LLM com
    *tool calling* faz esse papel: os métodos abaixo viram as ferramentas dele,
    e ele só escreve a explicação a partir do que as ferramentas devolvem.
    """

    def __init__(self):
        self.ing, self.rec, restr = carregar_base()
        self.guardiao = Guardiao(restr)
        self.leitor = LeitorDeNota(self.ing)
        self.planejador = Planejador(self.ing, self.rec, self.guardiao)
        self.comprador = Comprador(self.ing, self.planejador)

    def o_que_cozinhar(self, estado: Estado, n=5):
        linhas = []
        for nota, r, c in self.planejador.candidatas(estado)[:n]:
            faltam = [self.ing[i]["nome"] for i in r["itens"] if estado.estoque.get(i, 0) <= 0]
            extra = f" (falta: {', '.join(faltam)})" if faltam else " (tem tudo em casa)"
            linhas.append(f"- {r['nome']}: {self.planejador.explicar(c, estado.perfil.pesos)}{extra}")
        return "Sugestões para a semana:\n" + "\n".join(linhas)

    def o_que_comprar(self, estado: Estado, orcamento: float, refeicoes: int):
        res = self.comprador.resolver(estado, orcamento, refeicoes)
        if res is None:
            return (f"Com R$ {orcamento:.2f} não consegui fechar {refeicoes} refeições. "
                    "Opções: reduzir o número de refeições ou aumentar o orçamento.")
        semana = "\n".join(f"- {self.rec[k]['nome']} x{n}" for k, n in res["semana"])
        lista = "\n".join(
            f"- {n}x {self.ing[i]['nome']} ({self.ing[i]['embalagem_g']:.0f} g) "
            f"R$ {n * self.ing[i]['preco_embalagem']:.2f}" for i, n in res["lista"])
        return (f"Cardápio ({refeicoes} refeições):\n{semana}\n\n"
                f"Lista de compras (R$ {res['total']:.2f} de R$ {orcamento:.2f}):\n{lista}")

    def responder(self, estado: Estado, mensagem: str, **kw):
        aviso = self.guardiao.checar_mensagem(mensagem)   # o Guardião fala primeiro
        if aviso:
            estado.registrar("Guardião", "encaminhamento acionado")
            return aviso
        m = _norm(mensagem)
        if "comprar" in m or "orcamento" in m:
            return self.o_que_comprar(estado, kw["orcamento"], kw["refeicoes"])
        if "cozinh" in m or "faco" in m or "fazer" in m:
            return self.o_que_cozinhar(estado)
        return "Posso sugerir o que cozinhar com o que você tem ou montar uma lista dentro do orçamento."

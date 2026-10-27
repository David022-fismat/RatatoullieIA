"""
Agente Avaliador.

Recebe receitas propostas pelo Montador (em JSON) e, para cada uma:
  1. checa o formato            -> rejeita se faltar campo
  2. checa os ingredientes      -> rejeita se usar algo que não existe na base
  3. checa as quantidades       -> rejeita se a porção for absurda
  4. checa as restrições        -> VETO se tiver ingrediente proibido pelo perfil
  5. calcula a nota             -> só para as que passaram (Guia Alimentar + perfil)
  6. explica                    -> motivo da rejeição ou porquê da nota

Não usa LLM: mesma entrada, mesma resposta. Os motivos de rejeição saem em
texto curto para o Montador usar na próxima rodada.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# limites de gramas por porção (por pessoa) para pegar quantidades absurdas do LLM
LIMITE_PORCAO_G = {
    "cereal": 150, "leguminosa": 120, "proteina": 250, "laticinio": 200,
    "tuberculo": 350, "hortalica": 300, "fruta": 300, "tempero": 30,
    "gordura": 20,
}
CAMPOS_OBRIGATORIOS = {"nome", "porcoes", "tempo_min", "ingredientes"}


@dataclass
class Resultado:
    receita: dict
    aprovada: bool
    nota: float = 0.0
    motivos: list[str] = field(default_factory=list)       # por que foi rejeitada
    explicacao: str = ""                                     # por que tem essa nota
    detalhes: dict = field(default_factory=dict)             # características (0 a 1)


class Avaliador:
    def __init__(self, ingredientes: dict, restricoes: dict):
        self.ing = ingredientes            # id -> linha de ingredientes.csv
        self.restricoes = restricoes       # nome -> conjunto de ids proibidos

    # ------------------------------------------------------------ checagens
    def _formato(self, r):
        faltam = CAMPOS_OBRIGATORIOS - set(r)
        if faltam:
            return [f"faltam campos: {', '.join(sorted(faltam))}"]
        if not r["ingredientes"]:
            return ["receita sem ingredientes"]
        return []

    def _ingredientes_existem(self, r):
        desconhecidos = [i["id"] for i in r["ingredientes"] if i["id"] not in self.ing]
        return [f"use só ingredientes da base; não existe: {', '.join(desconhecidos)}"] if desconhecidos else []

    def _quantidades(self, r):
        motivos, porcoes = [], max(1, r["porcoes"])
        for i in r["ingredientes"]:
            cat = self.ing[i["id"]]["categoria"]
            por_pessoa = i["gramas"] / porcoes
            if i["gramas"] <= 0:
                motivos.append(f"quantidade inválida de {i['id']}")
            elif por_pessoa > LIMITE_PORCAO_G.get(cat, 300):
                motivos.append(f"{i['id']} demais: {por_pessoa:.0f} g por pessoa "
                               f"(máx. {LIMITE_PORCAO_G[cat]} g)")
        return motivos

    def _restricoes(self, r, perfil):
        motivos = []
        ids = {i["id"] for i in r["ingredientes"]}
        for nome in perfil.restricoes:
            proibidos = ids & self.restricoes.get(nome, set())
            if proibidos:
                motivos.append(f"não use {', '.join(sorted(proibidos))} (perfil: {nome})")
        return motivos

    # ------------------------------------------------------------ nota
    def _caracteristicas(self, r, perfil, estoque):
        itens = {i["id"]: i["gramas"] for i in r["ingredientes"]}
        total = sum(itens.values())
        cats = {self.ing[i]["categoria"] for i in itens}
        natural = sum(g for i, g in itens.items() if self.ing[i]["nova"] == "in natura") / total
        ultra = sum(g for i, g in itens.items() if self.ing[i]["nova"] == "ultraprocessado") / total
        gosto = (sum(i in perfil.gosta for i in itens) - sum(i in perfil.nao_gosta for i in itens))
        usa = sum(min(g, estoque.get(i, 0)) / (1 + self.ing[i]["dias_validade"] / 7)
                  for i, g in itens.items()) / total
        return {
            # Guia Alimentar: base in natura, poucos ultraprocessados, verdura/legume presente
            "natural": max(0.0, natural - ultra),
            "tem_vegetal": 1.0 if cats & {"hortalica", "fruta"} else 0.0,
            "gosto": max(-1.0, min(1.0, gosto / 2)),
            "rapidez": 1 - min(r["tempo_min"], 60) / 60,
            "usa_estoque": min(1.0, usa * 2),
        }

    def nutrientes_por_pessoa(self, r):
        """Soma os nutrientes da TACO (por 100 g) de cada ingrediente e divide pelas porções."""
        tot = {"kcal": 0.0, "proteina_g": 0.0, "fibra_g": 0.0, "sodio_mg": 0.0}
        colunas = {"kcal": "kcal_100g", "proteina_g": "proteina_g_100g",
                   "fibra_g": "fibra_g_100g", "sodio_mg": "sodio_mg_100g"}
        for i in r["ingredientes"]:
            linha = self.ing[i["id"]]
            for k, col in colunas.items():
                v = linha.get(col) or 0
                tot[k] += float(v) * i["gramas"] / 100
        p = max(1, r["porcoes"])
        return {k: round(v / p, 1) for k, v in tot.items()}

    def _explicar(self, c, pesos):
        frases = {"natural": "é baseada em comida in natura", "tem_vegetal": "tem verdura ou fruta",
                  "gosto": "tem o que você gosta", "rapidez": "é rápida",
                  "usa_estoque": "usa o que já tem e vai estragar"}
        top = sorted(((pesos.get(k, 1) * v, k) for k, v in c.items()), reverse=True)[:2]
        return ", ".join(frases[k] for v, k in top if v > 0.2) or "equilibra os critérios"

    # ------------------------------------------------------------ entrada principal
    def avaliar(self, r: dict, perfil, estoque: dict) -> Resultado:
        # ordem importa: só faz a próxima checagem se a anterior passou
        for checagem in (self._formato, self._ingredientes_existem):
            motivos = checagem(r)
            if motivos:
                return Resultado(r, False, motivos=motivos)
        motivos = self._restricoes(r, perfil) + self._quantidades(r)
        if r["tempo_min"] > perfil.tempo_max_min:
            motivos.append(f"demora {r['tempo_min']} min; o máximo do perfil é {perfil.tempo_max_min}")
        if motivos:
            return Resultado(r, False, motivos=motivos)

        c = self._caracteristicas(r, perfil, estoque)
        pesos = {**{k: 1.0 for k in c}, **perfil.pesos}
        nota = sum(pesos[k] * v for k, v in c.items())
        detalhes = {**c, "nutrientes_por_pessoa": self.nutrientes_por_pessoa(r)}
        return Resultado(r, True, nota=round(nota, 2), detalhes=detalhes,
                         explicacao=self._explicar(c, pesos))

    def avaliar_lote(self, receitas, perfil, estoque):
        """Devolve (aprovadas ordenadas pela nota, motivos para o Montador)."""
        res = [self.avaliar(r, perfil, estoque) for r in receitas]
        aprovadas = sorted((x for x in res if x.aprovada), key=lambda x: -x.nota)
        motivos = sorted({m for x in res if not x.aprovada for m in x.motivos})
        return aprovadas, motivos, res

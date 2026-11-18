"""
Montador por ingredientes (sem receitas): monta as combinações de cada refeição do cronograma.

Para cada refeição, cada combinação tem um alimento de cada grupo:
    almoço e jantar       : proteína + carboidrato + leguminosa (feijão) + legumes + fruta
    café da manhã, lanche : carboidrato + proteína + fruta
(O feijão tem grupo próprio no almoço e no jantar porque é assim que se come no Brasil: arroz E feijão E a
carne. Com o feijão no lugar da carne, o prato não chega à energia da refeição. Para tirar, é só remover
"leguminosa" de GRUPOS_REFEICAO.)
Os alimentos vêm da despensa (kb/cronograma/despensa.csv): os mais comidos naquela refeição e região na
POF 2017–2018, com a porção típica de quem come aquilo. Os nutrientes são os da TBCA sem receitas.

AS GRAMAS BATEM AS METAS DA DRI. Feijão, legumes e fruta ficam na porção típica. Proteína e carboidrato
são multiplicados por fatores f_p e f_c (entre 0,5 e 1,75 vez a porção típica, para a quantidade continuar
realista), em três passos:
  1. a proteína começa na porção típica (f_p = 1) e só sobe se o prato não atingir a META MÍNIMA de
     proteína da refeição:  f_p = max(1, (meta_prot − prot dos outros itens) / prot_p);
  2. o carboidrato completa a energia:  f_c = (meta_kcal − kcal dos outros itens − f_p·kcal_p) / kcal_c;
  3. se o carboidrato bateu no limite (0,5 ou 1,75), a proteína ajusta o que ainda falta ou sobra de
     energia, sem descer abaixo do necessário para a meta de proteína.
(kcal_p, prot_p: energia e proteína da porção típica do item de proteína; kcal_c, prot_c: idem para o
carboidrato.) As gramas são arredondadas de 5 em 5.
Antes disso, todas as porções típicas são multiplicadas pela ESCALA da pessoa: a energia da refeição dividida
pela de um adulto de referência de 2.000 kcal/dia (entre 0,75 e 1,6). As porções da POF são as de um adulto
médio; quem precisa de 3.000 kcal come porções maiores de tudo, inclusive feijão, legumes e fruta. Combinações que nem assim chegam perto da energia
(itens muito leves ou muito pesados) continuam na lista, e o Avaliador as descarta pela nota de bem-estar.

O Montador não escolhe nada: entrega TODAS as combinações com gramas e nutrientes. Quem veta, dá nota e
escolhe as 3 opções é o Avaliador (agents/avaliador_ingredientes.py).
"""
from __future__ import annotations

import itertools
import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
ARQ_DESPENSA = RAIZ / "kb" / "cronograma" / "despensa.csv"

GRUPOS_REFEICAO = {
    "cafe_da_manha": ["carboidrato", "proteina", "fruta"],
    "almoco": ["proteina", "carboidrato", "leguminosa", "legumes", "fruta"],
    "lanche": ["carboidrato", "proteina", "fruta"],
    "jantar": ["proteina", "carboidrato", "leguminosa", "legumes", "fruta"],
}
TOP_POR_GRUPO = {"leguminosa": 3}          # os outros grupos usam top_por_grupo
NOMES_REFEICAO = {"cafe_da_manha": "Café da manhã", "almoco": "Almoço", "lanche": "Lanche", "jantar": "Jantar"}
FATOR_MIN, FATOR_MAX = 0.5, 1.75
KCAL_REFERENCIA = 2000                     # as porções típicas da POF são de um adulto médio
ESCALA_MIN, ESCALA_MAX = 0.75, 1.6
NUTRIENTES = ["energia_kcal", "proteina_g", "carboidrato_total_g", "lipidios_g", "fibra_g", "sodio_mg"]

# subtipos: o que a pessoa pode gostar ou não (são as características que o bandit do Avaliador aprende)
SUBTIPOS = {
    "proteina": [("leguminosa", r"^feijao|lentilha|grao.de.bico|ervilha|soja"), ("aves", r"frango|galinha|peru"),
                 ("boi", r"\bboi\b|bovin|carne seca|charque|bife"), ("porco", r"porco|suin|pernil|lombo"),
                 ("peixe", r"peixe|sardinha|atum|camarao|pescad|tilapia|merluza"), ("ovo", r"^ovo"),
                 ("embutido", r"linguica|salsicha|presunto|mortadela|calabresa|salame"),
                 ("leite", r"^leite|bebida lactea|bebida vegetal"), ("queijo", r"queijo|requeijao"),
                 ("iogurte", r"iogurte|coalhada")],
    "carboidrato": [("arroz", r"^arroz"), ("massa", r"macarrao|massa"),
                    ("raiz", r"mandioca|aipim|macaxeira|inhame|cara\b|tapioca|farofa|beiju"),
                    ("batata", r"^batata"), ("pao", r"^pao|torrada|biscoito|bolo"),
                    ("milho", r"milho|cuscuz|polenta|fuba|pipoca"), ("aveia", r"aveia|granola|cereais")],
    "leguminosa": [("carioca", r"carioca"), ("preto", r"preto"), ("fradinho", r"fradinho|corda|macassar")],
    "legumes": [("folha_crua", r"alface|rucula|agriao|couve, crua|repolho, cru|acelga|chicoria"),
                ("cru", r"crua?\b|crua?,"), ("cozido", r"cozid|vapor|refogad|assad|drenad")],
    "fruta": [("banana", r"^banana"), ("citrica", r"laranja|tangerina|mexerica|limao|abacaxi|acerola|ponka"),
              ("tropical", r"mamao|manga|melao|melancia|acai|goiaba|caju"), ("temperada", r"^maca|^pera|^uva|morango")],
}


def sem_acento(t):
    return "".join(c for c in unicodedata.normalize("NFKD", str(t).lower()) if not unicodedata.combining(c))


def subtipo(grupo, descricao):
    n = sem_acento(descricao)
    for nome, rx in SUBTIPOS.get(grupo, []):
        if re.search(rx, n):
            return nome
    return "outro"


class MontadorIngredientes:
    def __init__(self, despensa: pd.DataFrame | None = None, regiao: str = "Brasil", top_por_grupo: int = 8):
        d = despensa if despensa is not None else pd.read_csv(
            ARQ_DESPENSA, dtype={"nutriscore": str, "id_base": str}).fillna({"nutriscore": "", "id_base": ""})
        if regiao not in set(d.regiao):
            regiao = "Brasil"                                   # região desconhecida: usa o Brasil inteiro
        self.regiao = regiao
        limite = d.grupo.map(TOP_POR_GRUPO).fillna(top_por_grupo)
        self.d = d[(d.regiao == regiao) & (d["rank"] <= limite)].copy()
        self.d["subtipo"] = [subtipo(g, n) for g, n in zip(self.d.grupo, self.d.descricao)]
        self.log: list[str] = []

    def itens(self, refeicao, grupo):
        return self.d[(self.d.refeicao == refeicao) & (self.d.grupo == grupo)].reset_index(drop=True)

    # ---------------------------------------------------------------- combinações com gramas ajustadas
    def combinacoes(self, refeicao: str, metas: dict) -> pd.DataFrame:
        """metas: as da refeição vindas da calculadora DRI (energia_kcal, proteina_g, fibra_g, sodio_mg_max...).
        Devolve uma linha por combinação, com as gramas de cada item e os totais de nutrientes."""
        grupos = GRUPOS_REFEICAO[refeicao]
        tabelas = [self.itens(refeicao, g) for g in grupos]
        if any(t.empty for t in tabelas):
            raise ValueError(f"despensa sem itens para {refeicao} em {self.regiao}")
        idx = np.array(list(itertools.product(*[range(len(t)) for t in tabelas])))      # (n, grupos)
        codigos = np.column_stack([t.codigo.to_numpy()[idx[:, k]] for k, t in enumerate(tabelas)])
        distintos = np.array([len(set(c)) == len(c) for c in codigos])   # o mesmo alimento em 2 grupos: fora
        idx = idx[distintos]
        escala = float(np.clip(metas["energia_kcal"] / (metas.get("fracao", 0.3) * KCAL_REFERENCIA),
                               ESCALA_MIN, ESCALA_MAX))
        porcao = escala * np.column_stack([t.porcao_g.to_numpy()[idx[:, k]] for k, t in enumerate(tabelas)])
        por100 = {c: np.column_stack([t[c].to_numpy()[idx[:, k]] for k, t in enumerate(tabelas)]) / 100
                  for c in NUTRIENTES}

        fator = np.ones_like(porcao)
        ip, ic = grupos.index("proteina"), grupos.index("carboidrato")
        fixos = [k for k in range(len(grupos)) if k not in (ip, ic)]
        kcal = por100["energia_kcal"] * porcao
        prot = por100["proteina_g"] * porcao
        kp, kc, pp, pc = kcal[:, ip], kcal[:, ic], prot[:, ip], prot[:, ic]
        alvo_e = metas["energia_kcal"] - kcal[:, fixos].sum(1)
        alvo_p = metas["proteina_g"] - prot[:, fixos].sum(1)
        eps = 1e-6
        # 1. proteína: porção típica, ou mais se faltar proteína (com o carboidrato na porção típica)
        fp_min = np.clip((alvo_p - pc) / np.maximum(pp, eps), 1, FATOR_MAX)
        fp = fp_min.copy()
        # 2. carboidrato completa a energia
        fc = np.clip((alvo_e - fp * kp) / np.maximum(kc, eps), FATOR_MIN, FATOR_MAX)
        # 3. o que o carboidrato não conseguiu, a proteína ajusta (sem ficar abaixo do mínimo de proteína)
        fp = np.clip((alvo_e - fc * kc) / np.maximum(kp, eps), np.minimum(fp_min, 1), FATOR_MAX)
        fp = np.maximum(fp, np.where(pp > eps, np.minimum(fp_min, FATOR_MAX), FATOR_MIN))
        fator[:, ip], fator[:, ic] = fp, fc
        gramas = np.maximum(np.round(porcao * fator / 5) * 5, 5)

        totais = {c: (por100[c] * gramas).sum(1) for c in NUTRIENTES}
        registros = [t.to_dict("records") for t in tabelas]
        linhas = []
        for n, combo in enumerate(idx):
            itens = []
            for k, g in enumerate(grupos):
                r = registros[k][combo[k]]
                itens.append({"grupo": g, "codigo": r["codigo"], "alimento": r["descricao"],
                              "gramas": float(gramas[n, k]), "porcao_tipica_g": float(r["porcao_g"]),
                              "subtipo": r["subtipo"], "id_base": r["id_base"]})
            linhas.append(itens)
        df = pd.DataFrame({"itens": linhas})
        for c in NUTRIENTES:
            df[c] = totais[c].round(1)
        df["desvio_energia"] = (df.energia_kcal / metas["energia_kcal"] - 1).round(3)
        df["codigos"] = [frozenset(i["codigo"] for i in it) for it in linhas]
        df["codigos_ordem"] = [tuple(i["codigo"] for i in it) for it in linhas]
        # tabela dos itens desta refeição (um por alimento): o Avaliador usa para a trava
        df.attrs["itens"] = pd.concat(tabelas).drop_duplicates("codigo").set_index("codigo")
        # atributos por item que o Avaliador usa (trava e qualidade)
        for col in [c for c in self.d.columns if c.startswith(("alergeno_", "dieta_"))] + ["nova"]:
            df[col] = list(np.column_stack([t[col].to_numpy()[idx[:, k]] for k, t in enumerate(tabelas)]))
        df["nutriscore"] = list(np.column_stack([t.nutriscore.to_numpy()[idx[:, k]] for k, t in enumerate(tabelas)]))
        df.attrs["escala"] = round(escala, 2)
        self.log.append(f"{refeicao}: {len(df)} combinações ({' × '.join(str(len(t)) for t in tabelas)}), "
                        f"porções × {escala:.2f}")
        return df

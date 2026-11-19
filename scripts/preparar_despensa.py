"""
Monta a DESPENSA do cronograma: os alimentos que o Montador combina, por região, refeição e grupo, com a
porção típica de quem come aquilo no Brasil.

    python scripts/preparar_despensa.py CAMINHO/consumo_alimentar_tabela.csv.gz

Entradas:
  * consumo alimentar da POF 2017–2018 (IBGE) já lido em tabela (uma linha por alimento comido, com região,
    refeição, código TBCA e quantidade em gramas). Não vai no repositório: é grande. A saída vai.
  * kb/som/tbca_som.csv: a base da TBCA sem receitas (nutrientes por 100 g, grupo do prato, NOVA,
    Nutri-Score, alérgenos, dietas e a ligação com os ingredientes do app).

Saída: kb/cronograma/despensa.csv — para cada região (as 5 e "Brasil"), refeição e grupo, os TOP alimentos
mais comidos naquela refeição, com a porção típica (mediana das gramas na POF) e os nutrientes POR 100 g.

Grupos (o que o Montador combina):
  almoço e jantar      : proteína (carnes, peixes, ovos e leguminosas que não são feijão), carboidrato,
                         leguminosa (feijões), legumes, fruta
  café da manhã, lanche: carboidrato, proteína (laticínios, ovos, frios), fruta
"""
import re
import sys
import unicodedata
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from agents.montador_ingredientes import serve_no_prato   # noqa: E402  (o mesmo filtro da troca pelo SOM)
BASE = RAIZ / "kb" / "som" / "tbca_som.csv"
SAIDA = RAIZ / "kb" / "cronograma" / "despensa.csv"
TOP = 10                    # alimentos por região × refeição × grupo
MIN_VEZES = 20              # alimento comido menos que isso na refeição/região não entra

REFEICOES = {"café da manhã": "cafe_da_manha", "almoço": "almoco", "lanche": "lanche", "jantar": "jantar"}
# grupo do prato (kb/som) -> grupo do cronograma, por refeição
PRINCIPAL = {"proteína animal": ["proteina"], "leguminosa": ["leguminosa", "proteina"],
             "base (cereal/tubérculo)": ["carboidrato"], "verdura/legume": ["legumes"], "fruta": ["fruta"]}
LEVE = {"proteína animal": ["proteina"], "laticínio": ["proteina"], "base (cereal/tubérculo)": ["carboidrato"],
        "fruta": ["fruta"]}
GRUPOS = {"almoco": PRINCIPAL, "jantar": PRINCIPAL, "cafe_da_manha": LEVE, "lanche": LEVE}
FEIJAO = re.compile(r"^feijao")          # feijão vai para o grupo leguminosa, não para o da proteína
NUTRIENTES = ["energia_kcal", "proteina_g", "carboidrato_total_g", "lipidios_g", "fibra_g", "sodio_mg"]


def sem_acento(t):
    return "".join(c for c in unicodedata.normalize("NFKD", str(t).lower()) if not unicodedata.combining(c))


def main(caminho_pof):
    base = pd.read_csv(BASE, dtype={"nutriscore": str, "id_base": str}).fillna({"nutriscore": "", "id_base": ""})
    pof = pd.read_csv(caminho_pof, usecols=["regiao", "refeicao", "adicao", "COD_TBCA", "QTD"])
    pof = pof[(pof.adicao == "não") & pof.refeicao.isin(REFEICOES) & (pof.QTD > 0)]
    pof["refeicao"] = pof.refeicao.map(REFEICOES)
    pof = pof.merge(base[["codigo", "grupo", "descricao"]], left_on="COD_TBCA", right_on="codigo")
    # vagem é Phaseolus como o feijão (a TBCA põe em leguminosas), mas no prato é legume
    vagem = pof.descricao.map(lambda d: sem_acento(d).startswith("vagem"))
    pof.loc[vagem, "grupo"] = "verdura/legume"
    pof["grupo_cron"] = [GRUPOS[r].get(g, []) for r, g in zip(pof.refeicao, pof.grupo)]
    pof = pof.explode("grupo_cron").dropna(subset=["grupo_cron"])
    eh_feijao = pof.descricao.map(lambda d: bool(FEIJAO.match(sem_acento(d))))
    pof = pof[~((pof.grupo_cron == "proteina") & eh_feijao)]
    pof = pof[pof.descricao.map(serve_no_prato)]
    brasil = pof.assign(regiao="Brasil")

    chaves = ["regiao", "refeicao", "grupo_cron", "codigo"]
    agg = (pd.concat([pof, brasil]).groupby(chaves)
           .agg(vezes=("QTD", "size"), porcao_g=("QTD", "median")).reset_index())
    agg = agg[agg.vezes >= MIN_VEZES]
    agg["rank"] = agg.groupby(["regiao", "refeicao", "grupo_cron"]).vezes.rank(ascending=False, method="first")
    agg = agg[agg["rank"] <= TOP].rename(columns={"grupo_cron": "grupo"})
    agg["porcao_g"] = (agg.porcao_g / 5).round().clip(lower=1) * 5            # múltiplos de 5 g

    extras = [c for c in base.columns if c.startswith(("alergeno_", "dieta_"))]
    agg = agg.merge(base[["codigo", "descricao", "grupo"] + NUTRIENTES + ["nova", "nutriscore", "id_base"] + extras]
                    .rename(columns={"grupo": "grupo_tbca"}), on="codigo")
    for c in NUTRIENTES:
        agg[c] = agg[c].fillna(0).round(2)                                    # por 100 g
    agg = agg.sort_values(["regiao", "refeicao", "grupo", "rank"])
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    agg.to_csv(SAIDA, index=False)
    print(f"despensa: {len(agg)} linhas, {agg.codigo.nunique()} alimentos -> {SAIDA.relative_to(RAIZ)}")
    print(agg.groupby(["refeicao", "grupo"]).codigo.nunique().unstack().to_string())


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])

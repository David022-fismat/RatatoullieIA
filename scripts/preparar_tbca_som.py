"""
Monta a tabela que o mapa SOM usa, a partir da TBCA tratada (fontes/TBCA_dados_modelo.xlsx), SÓ COM ALIMENTOS.

    python scripts/atualizar_som.py             # faz tudo abaixo, na ordem
    python scripts/limpar_receitas_tbca.py      # kb/som/tbca_receitas_removidas.csv (o que saiu e por quê)
    python scripts/ligar_ingredientes_tbca.py   # kb/som/ingrediente_tbca.csv  (ingrediente do app -> TBCA)
    python scripts/preparar_tbca_som.py         # kb/som/tbca_som.csv + kb/som/parametros_minmax.csv
    python scripts/treinar_som.py               # kb/som/som_tbca.npz

A planilha traz os 5.668 itens da TBCA, mas uns 3 mil são RECEITAS (salada, sopa, sanduíche, papa, "c/ batata"...),
que não interessam para trocar um ingrediente. Aqui:
  1. tiramos as receitas (regra em limpar_receitas_tbca.py);
  2. pegamos os 37 nutrientes por 100 g em unidades reais (aba nutrientes_limpos) dos alimentos que ficaram,
     preenchemos os vazios com a mediana da classe (dentro dos alimentos que ficaram) e normalizamos com
     Min-Max (sklearn MinMaxScaler) de novo, porque o mínimo e o máximo mudam sem as receitas: colunas n_*,
     ENTRADA do mapa;
  3. juntamos grupo NOVA, Nutri-Score, alérgenos e dietas (aba modelo), o "grupo do prato" e a ligação com
     os ingredientes do app.
"""
import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler

from limpar_receitas_tbca import eh_receita

RAIZ = Path(__file__).resolve().parent.parent
PLANILHA = RAIZ / "fontes" / "TBCA_dados_modelo.xlsx"
LIGACAO = RAIZ / "kb" / "som" / "ingrediente_tbca.csv"
SAIDA = RAIZ / "kb" / "som" / "tbca_som.csv"
PARAMETROS = RAIZ / "kb" / "som" / "parametros_minmax.csv"
TUBERCULOS = (r"^(batata|mandioca|aipim|macaxeira|inhame|cara\b|mandioquinha|farinha, mandioca|mandioca, farinha|"
              r"tapioca|polvilho|fecula)")


def sem_acento(t):
    return "".join(c for c in unicodedata.normalize("NFKD", str(t).lower()) if not unicodedata.combining(c))


def grupo_do_prato(classe, nome):
    c, n = sem_acento(classe), sem_acento(nome)
    if re.match(r"bebida vegetal|bebida, substituto do leite", n):
        return "laticínio"                 # bebidas vegetais fazem o papel do leite (e o trocam)
    if re.match(TUBERCULOS, n):
        return "base (cereal/tubérculo)"
    if c.startswith("cereais"):
        return "lanche/doce" if re.match(r"(biscoito|bolo|torta|cereal matinal|cookie|wafer)", n) else "base (cereal/tubérculo)"
    if c.startswith("leguminosas"):
        return "oleaginosa" if n.startswith("amendoim") else "leguminosa"
    regras = (("vegetais", "verdura/legume"), ("frutas", "fruta"), (("carnes", "pescados", "ovos"), "proteína animal"),
              ("leite", "laticínio"), ("gorduras", "gordura/óleo"), ("sementes", "oleaginosa"),
              (("produtos acucarados", "acucares"), "lanche/doce"), ("bebidas", "bebida"))
    for prefixo, g in regras:
        if c.startswith(prefixo):
            return g
    return "outros"                      # papas infantis, industrializados, miscelâneas, fast food


def main():
    m = pd.read_excel(PLANILHA, sheet_name="modelo")
    nut = pd.read_excel(PLANILHA, sheet_name="nutrientes_limpos")
    assert (m.codigo == nut.codigo).all(), "as abas modelo e nutrientes_limpos precisam estar na mesma ordem"
    fica = np.array([eh_receita(d, c) is None for d, c in zip(nut.descricao, nut.classe)])
    m, nut = m[fica].reset_index(drop=True), nut[fica].reset_index(drop=True)

    d = nut[["codigo", "descricao", "classe", "energia_kcal", "proteina_g", "carboidrato_total_g", "lipidios_g",
             "fibra_g", "sodio_mg"]].copy()
    d["grupo"] = [grupo_do_prato(c, n) for c, n in zip(d.classe, d.descricao)]
    d["nova"] = m[["nova_1", "nova_2", "nova_3", "nova_4"]].to_numpy().argmax(1) + 1
    letras = ["A", "B", "C", "D", "E"]
    ns = m[[f"nutriscore_{l}" for l in letras]].to_numpy()
    d["nutriscore"] = np.where(ns.sum(1) > 0, np.array(letras)[ns.argmax(1)], "")
    for c in m.columns:
        if c.startswith(("alergeno_", "dieta_")):
            d[c] = m[c]
    lig = pd.read_csv(LIGACAO)
    ids = lig.groupby("codigo_tbca").id_app.apply(lambda s: "|".join(sorted(set(s))))
    d["id_base"] = d.codigo.map(ids).fillna("")

    # entrada do mapa: os mesmos 37 nutrientes, imputados e normalizados só com os alimentos que ficaram
    nutrientes = [c[2:] for c in m.columns if c.startswith("n_")]
    X = nut[nutrientes].astype(float)
    d["faltantes_imputados"] = X.isna().sum(axis=1)
    X = X.fillna(X.groupby(nut.classe).transform("median")).fillna(X.median())
    scaler = MinMaxScaler()                                   # n = (x - mínimo) / (máximo - mínimo)
    N = pd.DataFrame(scaler.fit_transform(X), columns=["n_" + c for c in nutrientes]).round(5)
    d = pd.concat([d, N], axis=1)
    d.to_csv(SAIDA, index=False)
    pd.DataFrame({"nutriente": nutrientes, "minimo": scaler.data_min_, "maximo": scaler.data_max_}) \
        .to_csv(PARAMETROS, index=False)

    perdidos = set(lig.id_app) - set(i for v in d.id_base for i in v.split("|") if i)
    print(f"{len(d)} alimentos ({int((~fica).sum())} receitas fora), {len(nutrientes)} nutrientes de entrada, "
          f"{int((d.id_base != '').sum())} ligados ao app -> {SAIDA.relative_to(RAIZ)}")
    if perdidos:
        print(f"ATENÇÃO: ingredientes do app sem alimento na base: {sorted(perdidos)}")
    print(d.grupo.value_counts().to_string())


if __name__ == "__main__":
    main()

"""
Liga cada ingrediente da base do app (kb/ingredientes.csv) aos alimentos da TBCA que ele representa.
É o que permite trocar um ingrediente da receita por outro que o mapa SOM sugeriu.

    python scripts/ligar_ingredientes_tbca.py      # gera kb/som/ingrediente_tbca.csv

As regras são expressões regulares sobre a descrição da TBCA (minúscula, sem acento). Ficam até 4 alimentos
por ingrediente, os de nome mais simples, sem receitas (mesma regra de limpar_receitas_tbca.py). REVISE o CSV gerado se mudar alguma regra.
"""
import re
import unicodedata
import warnings
from pathlib import Path

import pandas as pd

from limpar_receitas_tbca import eh_receita

RAIZ = Path(__file__).resolve().parent.parent
PLANILHA = RAIZ / "fontes" / "TBCA_dados_modelo.xlsx"
SAIDA = RAIZ / "kb" / "som" / "ingrediente_tbca.csv"

REGRAS = {
 "arroz": r"^arroz, polido", "feijao": r"^feijao, carioca", "feijao_preto": r"^feijao, preto", "ovo": r"^ovo, galinha, inteiro",
 "frango": r"^carne, frango, peito", "coxa_sobrecoxa": r"^carne, frango, (coxa|sobrecoxa)", "carne_moida": r"^carne, boi.*moid",
 "carne_bovina": r"^carne, boi, acem(?! moid)", "pernil": r"porco, pernil", "linguica": r"^linguica", "bacon": r"^toucinho defumado|^bacon", "peixe": r"pescada", "grao_de_bico": r"grao.de.bico", "sardinha": r"^peixe, agua salgada, sardinha",
 "leite": r"^leite, vaca, integral(?!.*po\b)", "leite_po": r"^leite, vaca, integral.*\bpo\b", "queijo": r"^queijo, minas, frescal",
 "bebida_vegetal": r"^bebida vegetal|^bebida, substituto do leite", "farinha_milho": r"^milho, farinha",
 "fuba": r"^milho, (polenta/fuba|fuba)", "macarrao": r"^macarrao, trigo(?!, (instantaneo|intantaneo))", "farinha_trigo": r"^(trigo, farinha|farinha, trigo|farinha de trigo)",
 "trigo_quibe": r"^trigo, grao", "aveia": r"^aveia", "amido_milho": r"^amido, milho|milho, amido",
 "farinha_mandioca": r"^farinha, mandioca|^mandioca, farinha", "pao_forma": r"^pao, trigo, (branco|integral), forma", "mandioca": r"^mandioca \(aipim, macaxeira\), (s/ casca, )?(crua|cozida)|^mandioca, (crua|cozida)",
 "mandioquinha": r"mandioquinha|batata, baroa", "inhame": r"^inhame", "batata": r"^batata, inglesa", "tomate": r"^tomate, (cru|maduro)",
 "extrato_tomate": r"^tomate, extrato", "cebola": r"^cebola, (branca|roxa)", "alho": r"^alho, (cru|em po)", "cenoura": r"^cenoura",
 "abobrinha": r"^abobrinha", "moranga": r"abobora, moranga", "chuchu": r"^chuchu", "vagem": r"^vagem", "repolho": r"^repolho",
 "beterraba": r"^beterraba", "pimentao": r"^pimentao, verde", "milho_verde": r"^milho, verde, grao, enlatado",
 "couve": r"^couve, manteiga|^couve,", "alface": r"^alface", "azeitona": r"^azeitona, verde", "banana": r"^banana, prata",
 "laranja": r"^laranja, pera", "limao": r"^limao, (tahiti|cravo|galego)", "oleo": r"^oleo, soja", "maionese": r"^maionese(?! vegana)", "molho_soja": r"^molho, soja",
 "vinagre": r"^vinagre", "hortela": r"^hortela", "fermento": r"^fermento, quimico", "frango_inteiro": r"frango, inteiro", "figado": r"^carne, boi, figado",
 "camarao": r"^camarao, ", "manteiga": r"^manteiga, (?!cacau)", "azeite": r"^azeite, oliva", "dende": r"^azeite, dende", "mussarela": r"queijo, (mucarela|mussarela|mozarela)",
 "parmesao": r"queijo, parmesao", "farinha_rosca": r"^farinha de rosca", "milho_espiga": r"^milho, verde, grao, (cru|cozido)",
 "pupunha": r"^pupunha", "pequi": r"^pequi", "caju": r"^caju,(?!.*(castanha|suco))", "jilo": r"^jilo",
 "quiabo": r"^quiabo", "maxixe": r"^maxixe", "espinafre": r"^espinafre", "chicoria": r"^chicoria", "amendoim": r"^amendoim(?!.*pacoca)", "castanha_caju": r"^castanha de caju|^caju, castanha",
}

PRATO = r"carameliz|\((?!media|50%|70|aipim|macaxeira|maisena|bacon|mandioquinha)"   # além das receitas


def sem_acento(t):
    return "".join(c for c in unicodedata.normalize("NFKD", str(t).lower()) if not unicodedata.combining(c))


def main():
    warnings.filterwarnings("ignore", message="This pattern is interpreted")
    tb = pd.read_excel(PLANILHA, sheet_name="nutrientes_limpos")[["codigo", "descricao", "classe"]]
    tb = tb[[eh_receita(d, c) is None for d, c in zip(tb.descricao, tb.classe)]]
    tb["n"] = tb.descricao.map(sem_acento)
    tb = tb[~tb.n.str.contains(PRATO, regex=True)]
    linhas = []
    for iid, rx in REGRAS.items():
        c = tb[tb.n.str.contains(rx, regex=True)]
        c = c.assign(t=c.descricao.str.len()).sort_values("t").head(4)
        linhas += [{"id_app": iid, "codigo_tbca": r.codigo, "descricao_tbca": r.descricao} for r in c.itertuples()]
    m = pd.DataFrame(linhas)
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    m.to_csv(SAIDA, index=False)
    sem = sorted(set(REGRAS) - set(m.id_app))
    print(f"{m.id_app.nunique()} ingredientes ligados a {len(m)} alimentos da TBCA -> {SAIDA.relative_to(RAIZ)}")
    if sem:
        print("sem alimento na TBCA:", ", ".join(sem))


if __name__ == "__main__":
    main()

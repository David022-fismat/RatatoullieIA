"""
Constrói a base de conhecimento ampliada (kb/) a partir das fontes (fontes/).

Fontes (base padrão = grupo + Ministério da Saúde + receitas do LLM):
  - fontes/receitas_ministerio.csv : "Na Cozinha com as Frutas, Legumes e Verduras" (MS/UFMG, 2016,
                                      CC BY-NC-SA 4.0) e "Preparações Regionais Saudáveis" (MS, 2010)
  - fontes/receitas_llm.csv        : receitas geradas pelo LLM para lacunas, com coluna de revisão
  - fontes/taco_food.csv + taco_nutrients.csv : TACO 4ª ed. (NEPA/Unicamp), via repositório taco-api
  - fontes/*_grupo.csv : receitas e ingredientes que o grupo já tinha
  - (desligadas por padrão) merenda: transcricao_bh_2013.csv e cardapios/pratos_campinas.csv

Saídas (sobrescreve): kb/ingredientes.csv, kb/receitas.csv, kb/receita_ingrediente.csv,
kb/restricoes.csv, kb/substituicoes.csv e kb/RELATORIO_BASE.md

Rodar de novo é seguro: tudo é refeito a partir de fontes/.
"""
import csv
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
FONTES, KB = RAIZ / "fontes", RAIZ / "kb"

FATOR_ADULTO = 1.5      # per capita do manual é ESCOLAR; adulto ≈ 1,5×. REVISAR com alguém de nutrição.
INCLUIR_MINISTERIO = True           # receitas do Ministério da Saúde (base principal)
INCLUIR_LLM = True                  # receitas do LLM que passaram no Avaliador
INCLUIR_LLM_NAO_REVISADAS = True    # False = só as marcadas revisado_pelo_grupo=sim (use antes da entrega final)
INCLUIR_CAMPINAS = False            # pratos da merenda de Campinas (desligado a pedido do grupo)
INCLUIR_BH_COMPLEMENTARES = False   # receitas do manual escolar de BH
PORCOES = 2             # receitas da base servem 2 pessoas (mesmo padrão do protótipo)
TOLERANCIA = 0.15       # per_capita × 50 deve bater com a coluna "50 pessoas" em ±15%

# ---------------------------------------------------------------------------
# 1. Ingredientes: id do sistema -> nome, TACO, categoria, NOVA, validade, embalagem, preço
#    Preços são ESTIMATIVAS para o MVP (coluna fonte_preco); trocar por DIEESE ou levantamento.
# ---------------------------------------------------------------------------
INGREDIENTES = {
    # id: (nome, nome exato na TACO ou "", categoria, nova, dias_validade, embalagem_g, preco)
    "arroz":          ("arroz branco", "Arroz, tipo 1, cru", "cereal", "in natura", 365, 1000, 6.50),
    "feijao":         ("feijão carioca", "Feijão, carioca, cru", "leguminosa", "in natura", 180, 1000, 8.00),
    "feijao_preto":   ("feijão preto", "Feijão, preto, cru", "leguminosa", "in natura", 180, 1000, 8.50),
    "ovo":            ("ovo", "Ovo, de galinha, inteiro, cru", "proteina", "in natura", 21, 600, 9.00),
    "frango":         ("peito de frango", "Frango, peito, sem pele, cru", "proteina", "in natura", 3, 1000, 18.00),
    "coxa_sobrecoxa": ("coxa e sobrecoxa de frango", "Frango, coxa, com pele, crua", "proteina", "in natura", 3, 1000, 13.00),
    "carne_moida":    ("carne moída", "Carne, bovina, acém, moído, cru", "proteina", "in natura", 2, 500, 19.00),
    "carne_bovina":   ("carne bovina (acém)", "Carne, bovina, acém, sem gordura, cru", "proteina", "in natura", 3, 1000, 36.00),
    "pernil":         ("pernil suíno", "Porco, pernil, cru", "proteina", "in natura", 3, 1000, 24.00),
    "linguica":       ("linguiça de porco", "Lingüiça, porco, crua", "proteina", "processado", 10, 500, 14.00),
    "paio":           ("paio", "Lingüiça, porco, crua", "proteina", "processado", 30, 400, 15.00),
    "bacon":          ("bacon", "Toucinho, cru", "gordura", "processado", 30, 250, 12.00),
    "peixe":          ("filé de peixe (pescada)", "Pescada, filé, cru", "proteina", "in natura", 2, 500, 22.00),
    "grao_de_bico":   ("grão-de-bico", "Grão-de-bico, cru", "leguminosa", "in natura", 365, 500, 9.00),
    "sardinha":       ("sardinha em lata", "Sardinha, conserva em óleo", "proteina", "processado", 365, 125, 6.00),
    "leite":          ("leite integral", "Leite, de vaca, integral", "laticinio", "processado", 90, 1000, 5.50),
    "leite_po":       ("leite em pó integral", "Leite, de vaca, integral, pó", "laticinio", "processado", 180, 400, 18.00),
    "queijo":         ("queijo minas", "Queijo, minas, frescal", "laticinio", "processado", 10, 500, 22.00),
    "bebida_vegetal": ("bebida vegetal", "Soja, extrato solúvel, natural, fluido", "laticinio", "processado", 30, 1000, 9.00),
    "farinha_milho":  ("flocão de milho", "Farinha, de milho, amarela", "cereal", "in natura", 180, 500, 3.50),
    "fuba":           ("fubá", "Milho, fubá, cru", "cereal", "in natura", 180, 1000, 5.00),
    "canjiquinha":    ("canjiquinha de milho", "Milho, fubá, cru", "cereal", "in natura", 180, 500, 4.00),
    "macarrao":       ("macarrão", "Macarrão, trigo, cru", "cereal", "processado", 365, 500, 4.50),
    "farinha_trigo":  ("farinha de trigo", "Farinha, de trigo", "cereal", "in natura", 180, 1000, 5.50),
    "trigo_quibe":    ("trigo para quibe", "", "cereal", "in natura", 180, 500, 6.00),
    "aveia":          ("aveia em flocos", "Aveia, flocos, crua", "cereal", "in natura", 180, 250, 5.00),
    "amido_milho":    ("amido de milho", "Milho, amido, cru", "cereal", "processado", 365, 500, 7.00),
    "farinha_mandioca": ("farinha de mandioca", "Farinha, de mandioca, torrada", "cereal", "in natura", 180, 1000, 7.50),
    "pao_forma":      ("pão de forma", "Pão, trigo, forma, integral", "cereal", "ultraprocessado", 7, 500, 9.00),
    "mandioca":       ("mandioca", "Mandioca, crua", "tuberculo", "in natura", 5, 1000, 6.00),
    "mandioquinha":   ("mandioquinha", "Batata, baroa, crua", "tuberculo", "in natura", 7, 1000, 12.00),
    "inhame":         ("inhame", "Inhame, cru", "tuberculo", "in natura", 15, 1000, 8.00),
    "batata":         ("batata", "Batata, inglesa, crua", "tuberculo", "in natura", 15, 1000, 6.50),
    "tomate":         ("tomate", "Tomate, com semente, cru", "hortalica", "in natura", 6, 1000, 7.00),
    "extrato_tomate": ("extrato de tomate", "Tomate, extrato", "hortalica", "processado", 365, 340, 5.00),
    "cebola":         ("cebola", "Cebola, crua", "hortalica", "in natura", 30, 1000, 5.00),
    "alho":           ("alho", "Alho, cru", "tempero", "in natura", 60, 200, 5.00),
    "cenoura":        ("cenoura", "Cenoura, crua", "hortalica", "in natura", 15, 1000, 4.50),
    "abobrinha":      ("abobrinha", "Abobrinha, italiana, crua", "hortalica", "in natura", 7, 1000, 6.00),
    "moranga":        ("abóbora moranga", "Abóbora, moranga, crua", "hortalica", "in natura", 30, 1000, 4.00),
    "chuchu":         ("chuchu", "Chuchu, cru", "hortalica", "in natura", 10, 1000, 4.00),
    "vagem":          ("vagem", "Vagem, crua", "hortalica", "in natura", 5, 500, 6.00),
    "repolho":        ("repolho", "Repolho, branco, cru", "hortalica", "in natura", 15, 1000, 4.00),
    "beterraba":      ("beterraba", "Beterraba, crua", "hortalica", "in natura", 15, 1000, 5.00),
    "pimentao":       ("pimentão verde", "Pimentão, verde, cru", "hortalica", "in natura", 7, 500, 5.00),
    "milho_verde":    ("milho verde em lata", "Milho, verde, enlatado, drenado", "hortalica", "processado", 365, 170, 4.50),
    "couve":          ("couve", "Couve, manteiga, crua", "hortalica", "in natura", 4, 200, 3.00),
    "alface":         ("alface", "Alface, crespa, crua", "hortalica", "in natura", 4, 300, 3.50),
    "azeitona":       ("azeitona verde", "Azeitona, verde, conserva", "hortalica", "processado", 180, 200, 8.00),
    "banana":         ("banana", "Banana, prata, crua", "fruta", "in natura", 6, 1000, 5.50),
    "laranja":        ("laranja", "Laranja, pêra, crua", "fruta", "in natura", 15, 1000, 4.00),
    "limao":          ("limão", "Limão, tahiti, cru", "fruta", "in natura", 15, 1000, 5.00),
    "oleo":           ("óleo de soja", "Óleo, de soja", "gordura", "processado", 365, 900, 8.00),
    "maionese":       ("maionese", "Maionese, tradicional com ovos", "gordura", "ultraprocessado", 90, 500, 9.00),
    "molho_soja":     ("molho de soja (shoyu)", "", "tempero", "processado", 365, 150, 6.00),
    "vinagre":        ("vinagre", "", "tempero", "processado", 365, 750, 4.00),
    "hortela":        ("hortelã", "", "tempero", "in natura", 5, 50, 3.00),
    "fermento":       ("fermento em pó", "Fermento em pó, químico", "tempero", "processado", 180, 100, 4.00),
    # --- usados pelas receitas do Ministério da Saúde
    "frango_inteiro": ("frango inteiro", "Frango, inteiro, com pele, cru", "proteina", "in natura", 3, 1600, 22.00),
    "figado":         ("fígado bovino", "Carne, bovina, fígado, cru", "proteina", "in natura", 2, 500, 12.00),
    "camarao":        ("camarão seco", "Camarão, Rio Grande, grande, cru", "proteina", "processado", 90, 100, 12.00),
    "manteiga":       ("manteiga", "Manteiga, com sal", "gordura", "processado", 60, 200, 12.00),
    "azeite":         ("azeite de oliva", "Azeite, de oliva, extra virgem", "gordura", "processado", 365, 500, 30.00),
    "dende":          ("azeite de dendê", "Azeite, de dendê", "gordura", "processado", 365, 200, 9.00),
    "mussarela":      ("queijo mussarela", "Queijo, mozarela", "laticinio", "processado", 20, 200, 10.00),
    "parmesao":       ("queijo parmesão ralado", "Queijo, parmesão", "laticinio", "processado", 60, 50, 6.00),
    "farinha_rosca":  ("farinha de rosca", "Farinha, de rosca", "cereal", "processado", 180, 500, 6.00),
    "milho_espiga":   ("milho verde (espiga)", "Milho, verde, cru", "cereal", "in natura", 5, 600, 6.00),
    "pupunha":        ("pupunha", "Pupunha, cozida", "fruta", "in natura", 5, 500, 10.00),
    "pequi":          ("pequi", "Pequi, cru", "fruta", "in natura", 7, 500, 12.00),
    "caju":           ("caju", "Caju, cru", "fruta", "in natura", 4, 500, 8.00),
    "mamao_verde":    ("mamão verde", "Mamão, Formosa, cru", "hortalica", "in natura", 7, 1200, 6.00),
    "jilo":           ("jiló", "Jiló, cru", "hortalica", "in natura", 7, 500, 6.00),
    "quiabo":         ("quiabo", "Quiabo, cru", "hortalica", "in natura", 5, 500, 7.00),
    "maxixe":         ("maxixe", "Maxixe, cru", "hortalica", "in natura", 5, 500, 6.00),
    "espinafre":      ("espinafre", "Espinafre, Nova Zelândia, cru", "hortalica", "in natura", 4, 300, 4.00),
    "chicoria":       ("chicória", "Chicória, crua", "hortalica", "in natura", 4, 300, 4.00),
    "vinagreira":     ("vinagreira", "", "hortalica", "in natura", 4, 250, 4.00),
    "palma":          ("palma forrageira", "", "hortalica", "in natura", 7, 500, 5.00),
    "amendoim":       ("amendoim", "Amendoim, grão, cru", "leguminosa", "in natura", 180, 500, 10.00),
    "castanha_caju":  ("castanha de caju", "Castanha-de-caju, torrada, salgada", "leguminosa", "processado", 180, 100, 12.00),
}

# texto do ingrediente nas receitas do Ministério -> id (o 1º trecho que casar vale; None = ignorar)
MAPA_MINISTERIO = [
    ("oleo", "oleo"), ("azeite de dende", "dende"), ("azeite", "azeite"), ("manteiga", "manteiga"),
    ("dente de alho", "alho"), ("cebolinha", None), ("cebola", "cebola"), ("cenoura", "cenoura"),
    ("abobrinha", "abobrinha"), ("azeitona", "azeitona"), ("farinha de milho", "farinha_milho"),
    ("farinha de trigo", "farinha_trigo"), ("farinha de aveia", "aveia"), ("farinha de rosca", "farinha_rosca"),
    ("aveia", "aveia"), ("cheiro-verde", None), ("salsinha", None), ("hortela", "hortela"),
    ("chuchu", "chuchu"), ("leite", "leite"), ("ovo", "ovo"), ("amido de milho", "amido_milho"),
    ("queijo minas", "queijo"), ("queijo mussarela", "mussarela"), ("queijo", "parmesao"),
    ("mamao verde", "mamao_verde"), ("abobora", "moranga"), ("moranga", "moranga"),
    ("trigo para quibe", "trigo_quibe"), ("folha de repolho", "repolho"), ("carne moida", "carne_moida"),
    ("acem moido", "carne_moida"), ("acem", "carne_bovina"), ("pimentao", "pimentao"),
    ("arroz", "arroz"), ("molho de tomate", "tomate"), ("tomate", "tomate"), ("fermento", "fermento"),
    ("folha de couve", "couve"), ("fuba", "fuba"), ("batata", "batata"), ("peito de frango", "frango"),
    ("jilo", "jilo"), ("pupunha", "pupunha"), ("peixe", "peixe"), ("chicoria", "chicoria"),
    ("frango inteiro", "frango_inteiro"), ("pequi", "pequi"), ("vinagreira", "vinagreira"),
    ("maxixe", "maxixe"), ("quiabo", "quiabo"), ("palma", "palma"), ("inhame", "inhame"),
    ("castanha de caju", "castanha_caju"), ("amendoim", "amendoim"), ("camarao", "camarao"),
    ("caju", "caju"), ("figado", "figado"), ("espinafre", "espinafre"), ("espiga de milho", "milho_espiga"),
    ("vagem", "vagem"),
]
FONTES_MINISTERIO = {
    "NCFLV": "Na Cozinha com as Frutas, Legumes e Verduras (Ministério da Saúde/UFMG, 2016, CC BY-NC-SA 4.0)",
    "PRS": "Preparações Regionais Saudáveis (Ministério da Saúde, 2010)",
}

# nome que aparece no manual (normalizado) -> id. Itens "X ou Y" usam a 1ª opção.
SINONIMOS_MANUAL = {
    "carne bovina": "carne_bovina", "carne": "carne_bovina", "carne de bovina": "carne_bovina",
    "carne bovina moida": "carne_moida", "pernil": "pernil", "pernil moido": "pernil",
    "file peito de frango": "frango", "file de peito de frango": "frango", "peito de frango": "frango",
    "file de frango": "frango", "coxa e sobrecoxa de frango": "coxa_sobrecoxa",
    "paio": "paio", "linguica de pernil": "linguica", "bacon": "bacon",
    "sardinha": "sardinha", "ovo": "ovo", "ovos": "ovo",
    "arroz": "arroz", "feijao": "feijao", "feijao preto": "feijao_preto",
    "macarrao": "macarrao", "farinha de trigo": "farinha_trigo", "trigo para quibe": "trigo_quibe",
    "farinha de mandioca": "farinha_mandioca", "fuba": "fuba", "canjiquinha": "canjiquinha",
    "aveia": "aveia", "amido de milho": "amido_milho", "leite em po": "leite_po",
    "batata": "batata", "batata inglesa": "batata", "mandioca": "mandioca",
    "mandioquinha": "mandioquinha", "inhame": "inhame",
    "tomate": "tomate", "extrato de tomate": "extrato_tomate", "cebola": "cebola",
    "cebola ralada": "cebola", "alho": "alho", "alho puro": "alho", "cenoura": "cenoura",
    "abobrinha": "abobrinha", "moranga": "moranga", "chuchu": "chuchu", "vagem": "vagem",
    "repolho": "repolho", "repolho picado": "repolho", "margarina": "oleo", "beterraba": "beterraba",
    "pimentao": "pimentao", "milho verde": "milho_verde", "couve": "couve",
    "azeitona": "azeitona", "laranja": "laranja", "limao": "limao", "oleo": "oleo",
    "maionese": "maionese", "molho de soja": "molho_soja", "vinagre": "vinagre",
    "hortela": "hortela", "fermento em po": "fermento",
}
IGNORAR = {"sal", "agua", "colorifico", "caldo de cozimento da carne bovina", "agua para diluir o leite",
           "agua p/ diluir o leite", "agua para hidratar o trigo"}
ACOMPANHAMENTOS = {"Arroz Simples (Almoço)", "Feijão Simples", "Purê de Batata", "Batatas Coradas (sauté)",
                   "Molho Branco", "Molho Ferrugem", "Molho de Tomate", "Vinagrete", "Tabule"}
DESCARTAR_RECEITAS = {"Arroz Simples (Prato Único)"}       # duplicata em porção menor
REGIAO = {"Baião de Três": "Nordeste", "Tutu de Feijão": "Sudeste", "Feijão Tropeiro": "Sudeste"}

RESTRICOES = {   # restrição -> ids proibidos (consulta rígida do Guardião/Avaliador)
    "vegetariano": ["frango", "coxa_sobrecoxa", "carne_moida", "carne_bovina", "pernil", "linguica",
                    "paio", "bacon", "sardinha", "peixe", "frango_inteiro", "figado", "camarao"],
    "sem_lactose": ["leite", "leite_po", "queijo", "manteiga", "mussarela", "parmesao"],
    "alergia_ovo": ["ovo", "maionese", "pao_forma"],
    "celiaco": ["macarrao", "pao_forma", "farinha_trigo", "trigo_quibe", "aveia", "molho_soja",
                "farinha_rosca"],
    "sem_carne_vermelha": ["carne_moida", "carne_bovina", "pernil", "linguica", "paio", "bacon", "figado"],
}
SUBSTITUICOES = {   # "remover" = tirar o ingrediente sem trocar (temperos de carne)
    "frango": ["ovo", "sardinha", "feijao"], "coxa_sobrecoxa": ["frango", "ovo", "feijao"],
    "carne_moida": ["frango", "ovo", "feijao_preto"], "carne_bovina": ["frango", "ovo", "feijao"],
    "pernil": ["frango", "carne_bovina", "ovo"], "linguica": ["remover"], "paio": ["remover"],
    "bacon": ["remover"], "sardinha": ["ovo", "frango"], "peixe": ["sardinha", "frango", "ovo"],
    "grao_de_bico": ["feijao"], "frango_inteiro": ["coxa_sobrecoxa", "frango", "ovo"],
    "figado": ["carne_bovina", "ovo"], "camarao": ["remover"], "manteiga": ["oleo"],
    "mussarela": ["remover"], "parmesao": ["remover"], "farinha_rosca": ["farinha_milho"],
    "pequi": ["remover"], "pupunha": ["mandioca"], "palma": ["chuchu"], "jilo": ["abobrinha"],
    "quiabo": ["vagem"], "maxixe": ["chuchu"], "chicoria": ["couve"], "espinafre": ["couve"],
    "vinagreira": ["couve"], "ovo": ["frango", "sardinha", "queijo"],
    "leite": ["bebida_vegetal"], "leite_po": ["bebida_vegetal"], "queijo": ["ovo", "sardinha"],
    "maionese": ["remover"], "macarrao": ["arroz", "batata"], "farinha_trigo": ["amido_milho"],
    "trigo_quibe": ["arroz"], "aveia": ["remover"], "molho_soja": ["remover"],
    "pao_forma": ["farinha_milho", "mandioca"], "feijao": ["feijao_preto"], "feijao_preto": ["feijao"],
    "couve": ["repolho", "abobrinha"], "alface": ["repolho", "tomate"], "abobrinha": ["chuchu", "cenoura"],
    "cenoura": ["abobrinha", "beterraba"], "batata": ["mandioca", "mandioquinha"],
    "mandioca": ["batata", "inhame"], "tomate": ["cenoura"], "chuchu": ["abobrinha", "vagem"],
    "vagem": ["chuchu"], "moranga": ["cenoura"],
}


def norm(txt):
    txt = unicodedata.normalize("NFKD", txt.lower())
    return re.sub(r"\s+", " ", "".join(c for c in txt if not unicodedata.combining(c))).strip()


def numero(txt):
    m = re.search(r"\d+(?:\s*,\s*\d+)?", txt)
    return float(m.group(0).replace(" ", "").replace(",", ".")) if m else None


def gramas_per_capita(txt):
    """'25 g', '0, 5 g', '2 ml', '70' (sem unidade = g), '2 ml/g' -> gramas (ml ≈ g)."""
    return numero(txt)


def gramas_cinquenta(txt):
    """'1,25 kg' -> 1250; '400g' -> 400; '6 Litros' -> 6000; medidas caseiras -> None."""
    t = norm(txt)
    n = numero(t)
    if n is None or any(p in t for p in ("colher", "xicara", "unidade", "pitada")):
        return None
    if "kg" in t or "litro" in t:
        return n * 1000
    if re.search(r"\b(g|ml|gramas)\b", t) or t.endswith(("g", "ml")):
        return n
    return None


def ler_csv(caminho, delim=","):
    with open(caminho, encoding="utf-8") as f:
        return list(csv.DictReader(f, delimiter=delim))


def escrever_csv(caminho, campos, linhas):
    with open(caminho, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campos)
        w.writeheader()
        w.writerows(linhas)


def main():
    rel = []                                     # linhas do relatório
    # ---------- TACO
    taco_nome = {r["name"]: r["id"] for r in ler_csv(FONTES / "taco_food.csv")}
    taco_nut = {r["foodId"]: r for r in ler_csv(FONTES / "taco_nutrients.csv")}

    # ---------- receitas do manual
    linhas = ler_csv(FONTES / "transcricao_bh_2013.csv", delim=";")
    receitas = defaultdict(dict)                 # nome -> {id: gramas por pessoa (escolar)}
    divergencias, nao_mapeados, ignorados_opc = [], set(), 0
    for l in linhas:
        nome_rec, ing_txt = l["receita"].strip(), l["ingrediente"].strip()
        if nome_rec in DESCARTAR_RECEITAS:
            continue
        variante = re.search(r"\((prato unico|almoco|escola integrada)\)", norm(ing_txt))
        if variante and variante.group(1) == "prato unico":
            continue                             # fica a porção de almoço
        if "opcional" in norm(ing_txt):
            ignorados_opc += 1
            continue
        base = norm(re.sub(r"\(.*?\)", "", ing_txt))
        base = base.split(" ou ")[0].strip()     # "Sardinha ou Atum" -> sardinha
        if base in IGNORAR or base.startswith("agua") or base.startswith("caldo"):
            continue
        iid = SINONIMOS_MANUAL.get(base)
        if iid is None:
            nao_mapeados.add(ing_txt)
            continue
        pc = gramas_per_capita(l["per_capita"])
        c50 = gramas_cinquenta(l["cinquenta"])
        if pc is None:
            nao_mapeados.add(f"{ing_txt} (sem quantidade)")
            continue
        if c50 is not None and abs(pc * 50 - c50) > TOLERANCIA * c50:
            divergencias.append(f"{nome_rec} / {ing_txt}: per capita {l['per_capita']} × 50 = "
                                f"{pc * 50:.0f} g, mas a coluna diz {l['cinquenta']}")
        receitas[nome_rec][iid] = receitas[nome_rec].get(iid, 0) + pc

    # ---------- ingredientes (nutrientes da TACO)
    campos_nut = {"kcal": "kcal_100g", "protein": "proteina_g_100g", "carbohydrates": "carboidrato_g_100g",
                  "dietaryFiber": "fibra_g_100g", "lipids": "lipidios_g_100g", "sodium": "sodio_mg_100g"}
    sinonimos_antigos = {r["id"]: r["sinonimos"] for r in ler_csv(FONTES / "ingredientes_grupo.csv")}
    linhas_ing, sem_taco = [], []
    for iid, (nome, taco, cat, nova, val, emb, preco) in INGREDIENTES.items():
        linha = {"id": iid, "nome": nome, "nova": nova, "categoria": cat, "dias_validade": val,
                 "embalagem_g": emb, "preco_embalagem": f"{preco:.2f}",
                 "sinonimos": sinonimos_antigos.get(iid, nome),
                 "fonte_preco": "estimativa do grupo (revisar)", "taco_nome": taco}
        nut = taco_nut.get(taco_nome.get(taco, ""), {})
        if not taco:
            sem_taco.append(iid)
        elif not nut:
            raise SystemExit(f"Nome da TACO não encontrado: {taco!r} (ingrediente {iid})")
        for orig, dest in campos_nut.items():
            v = nut.get(orig, "")
            linha[dest] = "" if v in ("", "NA", "Tr", "*") else v
        linhas_ing.append(linha)
    escrever_csv(KB / "ingredientes.csv",
                 ["id", "nome", "nova", "categoria", "dias_validade", "embalagem_g", "preco_embalagem",
                  "sinonimos", *campos_nut.values(), "taco_nome", "fonte_preco"], linhas_ing)

    # ---------- cardápios de Campinas: frequência de cada prato e itens sem receita
    pratos_cp = ler_csv(FONTES / "pratos_campinas.csv", delim=";")
    derivadas = defaultdict(dict)
    for l in ler_csv(FONTES / "receitas_campinas_derivadas.csv", delim=";"):
        derivadas[l["receita"]][l["ingrediente"]] = float(l["per_capita_g"])
    cardapios = ler_csv(FONTES / "cardapios_campinas.csv", delim=";")
    freq, sem_receita = defaultdict(int), defaultdict(int)
    ignorar_item = re.compile(r"^(arroz( integral)?( com brocolis)?|feijao( preto| com .*)?|salada.*|pao|ervilha"
                              r"|gema de ovo|creme de milho|pure de .*|bolo .*|suco .*|macarrao( ao alho e oleo)?"
                              r"|maca|melao|melancia|mamao|banana|abacaxi|caqui|goiaba)$")
    for c in cardapios:
        for item in c["pratos"].split(" / "):
            it = norm(re.sub(r"\(.*?\)", "", item)).strip()
            achou = [p["prato"] for p in pratos_cp if re.search(p["padrao"], it)]
            if achou:
                freq[achou[0]] += 1
            elif not ignorar_item.match(it):
                sem_receita[item.strip()] += 1

    # ---------- receitas: grupo (r..) + Campinas (cp..) [+ BH complementares (bh..)]
    rec_grupo = ler_csv(FONTES / "receitas_grupo.csv")
    ri_grupo = ler_csv(FONTES / "receita_ingrediente_grupo.csv")
    for r in rec_grupo:
        r.update({"tipo": "prato", "fonte": "grupo", "frequencia_campinas": 0})
    linhas_rec, linhas_ri = list(rec_grupo), list(ri_grupo)

    def tempo_estimado(nome):
        n = norm(nome)
        if n.startswith(("molho", "vinagrete", "ovos mexidos")):
            return 15
        if any(p in n for p in ("forno", "assad", "torta", "quibe", "panela", "feijo", "tutu", "feijao",
                                "escondidinho", "panqueca", "carne em cubos", "risoto", "grao de bico", "sufle", "rocambole",
                                "kibe", "charuto", "cozidao", "caldeirada", "galinhada", "trouxinha")):
            return 50
        return 30

    def adicionar(rid, nome, itens, tipo, fonte, frequencia, regiao="Sudeste", fator=FATOR_ADULTO):
        tags = [t for t, proib in RESTRICOES.items() if not set(itens) & set(proib)]
        linhas_rec.append({"id": rid, "nome": nome, "regiao": regiao, "refeicao": "almoco|jantar",
                           "tempo_min": tempo_estimado(nome), "porcoes": PORCOES, "tags": "|".join(tags),
                           "tipo": tipo, "fonte": fonte, "frequencia_campinas": frequencia})
        for iid, g in itens.items():
            linhas_ri.append({"receita": rid, "ingrediente": iid, "gramas": round(g * fator * PORCOES)})

    # ---------- receitas do Ministério da Saúde (medidas caseiras -> gramas)
    from medidas import PADRAO_SEM_REGRA, gramas, norm as norm_m, quantidade
    problemas_ms, mapa_ms = [], []
    if INCLUIR_MINISTERIO:
        por_receita = defaultdict(list)
        for l in ler_csv(FONTES / "receitas_ministerio.csv", delim=";"):
            por_receita[l["receita"]].append(l)
        for k, (nome, linhas_r) in enumerate(por_receita.items(), start=1):
            itens = defaultdict(float)
            for l in linhas_r:
                txt = norm_m(l["ingrediente"])
                iid = next((v for chave, v in MAPA_MINISTERIO if chave in txt), "?")
                if iid is None:
                    continue
                if iid == "?":
                    problemas_ms.append(f"{nome}: ingrediente sem id: {l['ingrediente']}")
                    continue
                g, obs = gramas(l["ingrediente"], iid, l["quantidade"])
                if g is None:
                    problemas_ms.append(f"{nome}: {l['ingrediente']} ({l['quantidade']}): {obs}")
                    continue
                itens[iid] += g
            total = sum(itens.values())
            r0 = linhas_r[0]
            rend, rt = quantidade(r0["rendimento"]), norm_m(r0["rendimento"])
            if rend is None:                        # sem rendimento: ~250 g por porção
                porcoes = max(1.0, round(total / 250))
                problemas_ms.append(f"{nome}: sem rendimento; estimadas {porcoes:.0f} porções (250 g cada)")
            elif "unidade" in rt:                   # bolinhos, pedaços: ~2 por pessoa
                porcoes = rend / 2
            else:
                porcoes = rend
            escala = PORCOES / porcoes
            adicionar(f"ms{k:02d}", nome, {i: g * escala / PORCOES for i, g in itens.items()},
                      r0["tipo"], FONTES_MINISTERIO[r0["fonte"]], 0, r0["regiao"], fator=1.0)
            mapa_ms.append((nome, r0["regiao"], r0["fonte"], r0["tipo"], round(total * escala / PORCOES)))

    # ---------- receitas do LLM (lacunas), só as que passaram no Avaliador
    mapa_llm = []
    if INCLUIR_LLM and (FONTES / "receitas_llm.csv").exists():
        por_receita = defaultdict(list)
        for l in ler_csv(FONTES / "receitas_llm.csv", delim=";"):
            por_receita[l["receita"]].append(l)
        for k, (nome, linhas_r) in enumerate(por_receita.items(), start=1):
            r0 = linhas_r[0]
            revisada = norm(r0["revisado_pelo_grupo"]) == "sim"
            if not revisada and not INCLUIR_LLM_NAO_REVISADAS:
                continue
            escala = PORCOES / float(r0["porcoes"])
            adicionar(f"ia{k:02d}", nome,
                      {l["ingrediente"]: float(l["gramas"]) * escala / PORCOES for l in linhas_r},
                      "prato", "Gerada por IA (Claude) para lacuna: " + r0["lacuna"]
                      + ("; revisada pelo grupo" if revisada else "; PENDENTE de revisão do grupo"),
                      0, r0["regiao"], fator=1.0)
            linhas_rec[-1]["tempo_min"] = r0["tempo_min"]
            mapa_llm.append((nome, r0["lacuna"], "sim" if revisada else "pendente"))

    usadas_bh, mapa_cp = set(), []
    for k, p in enumerate(sorted(pratos_cp, key=lambda p: -freq[p["prato"]]) if INCLUIR_CAMPINAS else [],
                          start=1):
        if p["receita"].startswith("bh:"):
            nome_bh = p["receita"][3:]
            itens = receitas[nome_bh]                     # KeyError = nome do manual digitado errado
            usadas_bh.add(nome_bh)
            fonte = f"Cardápio escolar de Campinas; quantidades do manual PBH 2013 ({nome_bh})"
        else:
            itens = derivadas[p["prato"]]
            if not itens:
                raise SystemExit(f"Prato derivado sem ingredientes: {p['prato']}")
            fonte = "Cardápio escolar de Campinas; quantidades derivadas de componentes do manual PBH 2013"
        adicionar(f"cp{k:02d}", p["prato"], itens, p["tipo"], fonte, freq[p["prato"]])
        mapa_cp.append((p["prato"], freq[p["prato"]], p["receita"]))

    if INCLUIR_BH_COMPLEMENTARES:
        for k, (nome_rec, itens) in enumerate(sorted(receitas.items()), start=1):
            if nome_rec not in usadas_bh:
                adicionar(f"bh{k:02d}", nome_rec.replace(" (Almoço)", ""), itens,
                          "acompanhamento" if nome_rec in ACOMPANHAMENTOS else "prato",
                          "Manual de Receitas da Alimentação Escolar, PBH 2013", 0,
                          REGIAO.get(nome_rec, "Sudeste"))
    escrever_csv(KB / "receitas.csv",
                 ["id", "nome", "regiao", "refeicao", "tempo_min", "porcoes", "tags", "tipo", "fonte",
                  "frequencia_campinas"], linhas_rec)
    escrever_csv(KB / "receita_ingrediente.csv", ["receita", "ingrediente", "gramas"], linhas_ri)

    # ---------- restrições e substituições
    escrever_csv(KB / "restricoes.csv", ["restricao", "tipo", "ingredientes_excluidos"],
                 [{"restricao": k, "tipo": "escolha" if k in ("vegetariano", "sem_carne_vermelha") else "saude",
                   "ingredientes_excluidos": "|".join(v)} for k, v in RESTRICOES.items()])
    escrever_csv(KB / "substituicoes.csv", ["ingrediente", "substitutos"],
                 [{"ingrediente": k, "substitutos": "|".join(v)} for k, v in SUBSTITUICOES.items()])

    # ---------- checagens de integridade
    ids_ing = set(INGREDIENTES)
    usados = {l["ingrediente"] for l in linhas_ri}
    for faltando in sorted(usados - ids_ing):
        raise SystemExit(f"Receita usa ingrediente sem cadastro: {faltando}")
    for lista in list(RESTRICOES.values()) + list(SUBSTITUICOES.values()):
        for i in lista:
            if i != "remover" and i not in ids_ing:
                raise SystemExit(f"Restrição/substituição cita id inexistente: {i}")

    # ---------- relatório
    contagem = defaultdict(int)
    for r in linhas_rec:
        contagem[r["id"][:2]] += 1
    rel += ["# Relatório da base de conhecimento", "",
            f"- Receitas: {len(linhas_rec)} no total "
            f"({sum(r['tipo'] == 'acompanhamento' for r in linhas_rec)} acompanhamentos)",
            f"  - grupo: {len(rec_grupo)}",
            f"  - Ministério da Saúde: {contagem['ms']}",
            f"  - geradas pelo LLM: {contagem['ia']} "
            f"({sum(1 for *_, s in mapa_llm if s == 'pendente')} pendentes de revisão)",
            *([f"  - merenda de Campinas: {contagem['cp']}"] if contagem["cp"] else []),
            *([f"  - manual escolar de BH: {contagem['bh']}"] if contagem["bh"] else []),
            f"- Ingredientes: {len(linhas_ing)} ({len(linhas_ing) - len(sem_taco)} com nutrientes da TACO)", "",
            "## Receitas do Ministério da Saúde", "",
            "| Receita | Região | Fonte | Tipo | g por pessoa |", "|---|---|---|---|---|",
            *[f"| {n} | {rg} | {f} | {t} | {g} |" for n, rg, f, t, g in mapa_ms], "",
            "## Receitas geradas pelo LLM", "",
            "| Receita | Lacuna que cobre | Revisada pelo grupo |", "|---|---|---|",
            *([f"| {n} | {lac} | {s} |" for n, lac, s in mapa_llm] or ["| - | - | - |"]), "",
            "## Conversão de medidas caseiras: avisos", "",
            *([f"- {x}" for x in problemas_ms + sorted(set(PADRAO_SEM_REGRA))] or ["- nenhum"]), "",
            "## Ingredientes sem correspondência na TACO", "", *[f"- {i}" for i in sem_taco], "",
            "## Pendências para o grupo", "",
            "- Revisar as receitas do LLM e marcar revisado_pelo_grupo=sim em fontes/receitas_llm.csv;"
            " antes da entrega, usar INCLUIR_LLM_NAO_REVISADAS = False.",
            "- Medidas caseiras viraram gramas por valores de referência aproximados (scripts/medidas.py);"
            " refinar com a tabela de medidas referidas do IBGE (POF 2008-2009).",
            "- As receitas do Ministério não informam tempo de preparo: foi estimado por tipo de prato.",
            "- Preços são estimativas: trocar por DIEESE ou levantamento em mercado.",
            "- Transcrições feitas por leitura automática dos PDFs: conferir algumas com o original."]
    (KB / "RELATORIO_BASE.md").write_text("\n".join(rel) + "\n", encoding="utf-8")
    print("\n".join(rel))


if __name__ == "__main__":
    main()

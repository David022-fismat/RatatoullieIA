"""
Conversão de medidas caseiras em gramas.

VALORES DE REFERÊNCIA APROXIMADOS, para o MVP. Para refinar, use a "Tabela de medidas referidas
para os alimentos consumidos no Brasil" (IBGE, POF 2008-2009) e ajuste os dicionários abaixo.
Toda conversão que cai num valor padrão (sem regra específica) é registrada para o relatório.
"""
import re
import unicodedata

VOLUME_ML = {   # medida -> mililitros
    "xicara": 240, "copo americano": 190, "copo duplo": 240, "copo": 190,
    "colher de sopa": 15, "colher de sobremesa": 10, "colher de cha": 5, "colher de cafe": 2.5,
    "prato de sopa": 300, "prato de sobremesa": 200, "litro": 1000, "ml": 1,
}
DENSIDADE = {   # id do ingrediente (ou estado no texto) -> g/ml. Padrão: 1.0
    "oleo": 0.9, "azeite": 0.9, "dende": 0.9, "manteiga": 0.95, "leite": 1.03,
    "farinha_trigo": 0.53, "farinha_milho": 0.35, "farinha_mandioca": 0.6, "farinha_rosca": 0.45,
    "fuba": 0.55, "amido_milho": 0.6, "aveia": 0.4, "trigo_quibe": 0.7, "fermento": 0.9,
    "arroz": 0.8, "arroz cozido": 0.65, "feijao": 0.8, "azeitona": 0.55, "carne_moida": 0.9,
    "queijo": 0.45, "mussarela": 0.45, "parmesao": 0.4, "amendoim": 0.6,
    "amassad": 0.9, "hortela": 0.2, "picad": 0.55, "em cubos": 0.55, "em rodelas": 0.5,
    "camarao": 0.35, "palma": 0.6, "vagem": 0.45, "tomate": 0.6,
}
ESTADO = {   # estado do alimento no texto tem prioridade sobre o ingrediente
    "arroz cozido": 0.65, "amassad": 0.9, "molho de tomate": 1.05, "ralad": 0.4,
}
PESO_UNIDADE = {   # trecho do texto do ingrediente -> gramas por unidade (o 1º que casar vale)
    "dente de alho": 5, "folha de repolho": 25, "folha de couve": 25, "ovo": 50,
    "cebola pequena": 70, "cebola media": 100, "cebola grande": 150, "cebola": 100,
    "cenoura grande": 150, "cenoura": 100, "abobrinha": 250, "tomate": 100,
    "batata media": 150, "batata": 150, "pimentao grande": 200, "pimentao": 150,
    "peito de frango": 300, "frango inteiro": 1600, "peixe em postas": 1000, "figado": 450,
    "jilo": 30, "quiabo": 15, "maxixe": 20, "pupunha": 25, "pequi": 30, "castanha": 3,
    "inhame grande": 400, "abobora pequena": 1000, "mamao verde": 1200, "caju grande": 150,
    "espiga de milho": 150, "chicoria": 300, "vinagreira": 250, "espinafre": 300,  # "maço"
}
PADRAO_SEM_REGRA: list[str] = []


def norm(t):
    t = unicodedata.normalize("NFKD", t.lower())
    return re.sub(r"\s+", " ", "".join(c for c in t if not unicodedata.combining(c))).strip()


def quantidade(txt):
    """'1 ½', '2 ½', '⅓', '1/4', '1 e 1/4', '3,5', '10' -> float"""
    t = txt.replace("½", " 1/2").replace("⅓", " 1/3").replace("¼", " 1/4").replace("¾", " 3/4")
    t = t.replace(" e ", " ").replace(",", ".")
    total, achou = 0.0, False
    for tok in re.findall(r"\d+/\d+|\d+(?:\.\d+)?", t):
        achou = True
        if "/" in tok:
            a, b = tok.split("/")
            total += float(a) / float(b)
        else:
            total += float(tok)
    return total if achou else None


def gramas(ingrediente_txt, iid, qtd_txt):
    """Converte '½ xícara' de 'óleo' (id oleo) em gramas. Devolve (gramas, observação)."""
    q, t, ing = quantidade(qtd_txt), norm(qtd_txt), norm(ingrediente_txt)
    t = t.replace("colheres", "colher").replace("xicaras", "xicara").replace("copos", "copo")
    if q is None:
        return None, "sem quantidade"
    if re.search(r"\bkg\b", t):
        return q * 1000, ""
    if re.search(r"\d\s*g\b|\bg$|gramas", t):
        return q, ""
    for medida, ml in VOLUME_ML.items():
        if medida in t:
            estado = next((d for k, d in ESTADO.items() if k in ing), None)
            dens = estado if estado is not None else DENSIDADE.get(iid)
            if dens is None:
                dens = next((d for k, d in DENSIDADE.items() if k in ing), None)
            if dens is None:
                dens = 1.0
                PADRAO_SEM_REGRA.append(f"densidade padrão 1,0 g/ml: {ingrediente_txt} ({qtd_txt})")
            return q * ml * dens, ""
    if "unidade" in t or "maco" in t or re.fullmatch(r"[\d\s/.,]+", t):
        peso = next((g for k, g in PESO_UNIDADE.items() if k in ing), None)
        if peso is None:
            return None, f"sem peso por unidade para '{ingrediente_txt}'"
        return q * peso, ""
    return None, f"medida não reconhecida: '{qtd_txt}'"

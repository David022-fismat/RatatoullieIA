"""
Extrai as receitas COMPLETAS (ingredientes + modo de preparo) dos dois livros do Ministério da Saúde
e grava fontes/receitas_ms_texto.csv (uma linha por receita). É a base de texto do RAG.

  - "Na Cozinha com as Frutas, Legumes e Verduras" (MS/UFMG, 2016, CC BY-NC-SA 4.0)   -> NCFLV
  - "Preparações Regionais Saudáveis" (MS, 2010)                                       -> PRS

Só precisa rodar se quiser refazer o CSV (ele já vem pronto no repositório):
    pip install pdfplumber
    python scripts/extrair_livros_ms.py CAMINHO/Na_cozinha....pdf CAMINHO/preparacoes_regionais....pdf

Como funciona:
  - NCFLV: uma coluna por página. O título da receita é o texto em fonte 17; cabeçalho e rodapé
    (fonte <= 8, número da página em fonte 14) são descartados. A seção vem do sumário do livro.
  - PRS: cada página do PDF é uma página dupla do livro; cortamos ao meio e lemos cada metade.
    Os ingredientes vêm da tabela (nome | medida caseira); preparo, rendimento e informação
    nutricional vêm do texto. Uma receita pode continuar na metade seguinte.
"""
import csv
import re
import sys
from collections import Counter
from pathlib import Path

import pdfplumber

RAIZ = Path(__file__).resolve().parent.parent
SAIDA = RAIZ / "fontes" / "receitas_ms_texto.csv"

# ------------------------------------------------------------------ Na Cozinha com as FLV (NCFLV)
SECOES_NCFLV = [(44, "Saladas"), (52, "Caldos, sopas e molhos"), (59, "Molhos frios para saladas"),
                (63, "Preparações para almoço e jantar"), (77, "Sobremesas"),
                (88, "Preparações para lanches"), (99, "Bebidas")]
PAGINAS_NCFLV = range(44, 112)          # capítulo de receitas (antes das referências)
CABECALHO_SECAO = re.compile(r"(Preparações para lanches|Preparações para almoço e jantar|"
                             r"Molhos frios para saladas|Caldos, sopas e molhos)\b")


def _secao_ncflv(pagina):
    return [nome for p, nome in SECOES_NCFLV if pagina >= p][-1]


def _linhas_ncflv(caminho):
    with pdfplumber.open(caminho) as pdf:
        for n in PAGINAS_NCFLV:
            p = pdf.pages[n - 1]
            for l in p.extract_text_lines(return_chars=True):
                tam = Counter(round(c["size"]) for c in l["chars"]).most_common(1)[0][0]
                if tam <= 8 or tam == 14 or tam >= 22:     # cabeçalho, nº da página, título de seção
                    continue
                yield n, tam, l["text"].strip(), l["x1"] > p.width * 0.80   # True = linha quebrada


def _subtitulo(t):
    return (t.isupper() and not re.search(r"\d", t) and len(t) < 40
            and not t.startswith(("INGREDIENTES", "MODO", "RENDIMENTO", "DICA")))


def _junta(anterior, t):
    return anterior[:-1] + t if anterior.endswith("-") else anterior + " " + t


def extrair_ncflv(caminho):
    receitas, atual, modo, titulo, sub, quebrou = [], None, None, [], "", False
    for pag, tam, t, cheia in _linhas_ncflv(caminho):
        if tam == 17:                                   # título (pode ocupar 2 linhas)
            if modo != "titulo":
                titulo = []
            titulo.append(t)
            modo = "titulo"
            continue
        if CABECALHO_SECAO.match(t) and len(t) < 70:
            continue
        if t.startswith("INGREDIENTES") and len(t) < 30:
            if not titulo and atual is not None:        # 2º bloco da mesma receita (ex.: recheio)
                modo, sub, quebrou = "ing", "", False
                continue
            atual = {"livro": "NCFLV", "pagina": pag, "nome": " ".join(titulo),
                     "secao": _secao_ncflv(pag), "regiao": "Brasil", "ingredientes": [],
                     "preparo": [], "rendimento": "", "porcao": "", "observacoes": "", "nutricao": {}}
            receitas.append(atual)
            titulo, modo, sub, quebrou = [], "ing", "", False
            continue
        if atual is None:
            continue
        if t.startswith("MODO DE PREPARO"):
            if atual["preparo"]:
                atual["preparo"].append((sub or "continuação").upper() + ":")
            modo, quebrou = "prep", False
            continue
        if re.match(r"(RENDIMENTO|Rendimento)\s*:", t):
            atual["rendimento"] = t.split(":", 1)[1].strip().rstrip(".")
            modo = "obs"
            continue
        if re.match(r"(DICAS?|Dicas?)\s*:", t):
            t = t.split(":", 1)[1].strip()
            modo = "obs"
        if modo == "ing":
            if _subtitulo(t):
                sub, quebrou = t.lower(), False
                continue
            ing = atual["ingredientes"]
            aberto = ing and ing[-1][1].count("(") > ing[-1][1].count(")")
            if ing and ((quebrou and re.match(r"[a-zà-ú(]", t)) or aberto):
                ing[-1] = (ing[-1][0], _junta(ing[-1][1], t))
            else:
                ing.append((sub, t))
            quebrou = cheia
        elif modo == "prep":
            pr = atual["preparo"]
            if _subtitulo(t):
                pr.append(t + ":")
            elif pr and not pr[-1].endswith(":") and not re.match(r"\d+\s*[.)-]", t):
                pr[-1] = _junta(pr[-1], t)
            else:
                pr.append(t)
        elif modo == "obs":
            atual["observacoes"] = _junta(atual["observacoes"], t) if atual["observacoes"] else t
    return receitas


# ------------------------------------------------------------------ Preparações Regionais (PRS)
NUTRI = r"(Valor energético|Carboidratos|Proteínas|Gorduras totais|Fibra alimentar)\s+([\d.,]+)"


def _metades(caminho):
    with pdfplumber.open(caminho) as pdf:
        for i, p in enumerate(pdf.pages):
            for caixa in ((0, 0, p.width / 2, p.height), (p.width / 2, 0, p.width, p.height)):
                c = p.crop(caixa)
                yield i + 1, (c.extract_text() or ""), c.extract_tables()


def _titulo(linhas):
    t = re.sub(r"\s+", " ", " ".join(l.strip() for l in linhas)).strip()
    return t[:1].upper() + t[1:]          # a fonte do título perde a maiúscula inicial


def _passos(linhas):
    """Junta linhas quebradas; nova linha só em passo numerado ou subtítulo terminado em ':'."""
    out = []
    for l in linhas:
        if out and not re.match(r"\d+\s*\.", l) and not l.endswith(":") and not out[-1].endswith(":"):
            out[-1] = _junta(out[-1], l)
        else:
            out.append(l)
    return out


def extrair_prs(caminho):
    receitas, regiao, atual, modo = [], None, None, None
    for pag, txt, tabelas in _metades(caminho):
        linhas = txt.split("\n")
        m = re.search(r"REGIÃO (NORTE|SUL|CENTRO-OESTE|NORDESTE|SUDESTE)", txt)
        if m and "Ingredientes" not in txt:
            regiao = m.group(1).title().replace("Centro-oeste", "Centro-Oeste")
            continue
        if regiao is None:                      # páginas de apresentação
            continue
        k_ing = next((k for k, l in enumerate(linhas) if l.startswith("Ingredientes")), None)
        inicio = 0
        if k_ing is not None:
            atual = {"livro": "PRS", "pagina": pag, "nome": _titulo(linhas[:k_ing]), "secao": "",
                     "regiao": regiao, "ingredientes": [], "preparo": [], "rendimento": "",
                     "porcao": "", "observacoes": [], "nutricao": {}}
            receitas.append(atual)
            sub = ""
            for tab in tabelas[:2]:
                for row in tab:
                    nome = re.sub(r"\s+", " ", (row[0] or "")).strip()
                    qtd = re.sub(r"\s+", " ", (row[1] or "")).strip() if len(row) > 1 else ""
                    if not nome:
                        continue
                    if nome.lower().startswith("ingredientes"):
                        mm = re.search(r"\(\s*(.*?)\s*\)", nome)
                        sub = mm.group(1).lower() if mm else sub
                    elif not qtd and (nome.endswith(":") or nome.isupper()):
                        sub = nome.rstrip(":").lower()
                    else:
                        atual["ingredientes"].append((sub, f"{nome}: {qtd}" if qtd else nome))
            modo, inicio = "ing", k_ing + 1
        if atual is None:
            continue
        for l in linhas[inicio:]:
            s = l.strip()
            if not s or re.fullmatch(r"\d{1,3}", s):
                continue
            if s.endswith(":") and len(s) < 40:
                s = s.upper()                    # "EtAPA CEnOuRA:" (versalete) -> "ETAPA CENOURA:"
            low = s.lower()
            if low.startswith("modo de preparo"):
                modo = "prep"
            elif low.startswith("rendimento"):
                atual["rendimento"], modo = s.split(":", 1)[1].strip(), "obs"
            elif low.startswith("porção (medida caseira)"):
                atual["porcao"] += f" ({s.split(':', 1)[1].strip()})"
            elif low.startswith("porção:"):
                atual["porcao"] = s.split(":", 1)[1].strip() + atual["porcao"]
            elif "informação nutricional" in low:
                modo = "nut"
                for k, v in re.findall(NUTRI, s):
                    atual["nutricao"][k] = v.replace(",", ".")
            elif modo == "nut" and re.match(NUTRI, s):
                k, v = re.match(NUTRI, s).groups()
                atual["nutricao"][k] = v.replace(",", ".")
            elif modo == "prep":
                atual["preparo"].append(s)
            elif modo in ("obs", "nut"):
                modo = "obs"
                atual["observacoes"].append(s)
    for r in receitas:
        r["preparo"] = _passos(r["preparo"])
        r["observacoes"] = " ".join(_passos(r["observacoes"]))
    return receitas


# ------------------------------------------------------------------ tipo de preparação
def tipo(r):
    n = r["nome"].lower()
    sec = r["secao"]
    if sec == "Bebidas":
        return "bebida"
    if sec == "Saladas" or n.startswith("salada"):
        return "salada"
    if sec in ("Molhos frios para saladas",) or n.startswith(("molho", "maionese")):
        return "molho"
    if n.startswith("fundo"):
        return "base"
    if sec == "Sobremesas" or n.startswith(("pudim", "sagu", "geleia", "doce", "cartola", "purê de maçã")):
        return "sobremesa"
    if sec == "Preparações para lanches" or n.startswith(("pão", "bolo")):
        return "lanche"
    if n.startswith(("farofa", "purê", "mamão verde", "arroz", "angu", "virado de vagem",
                     "vatapá", "feijão tropeiro", "quiabo ao forno")):
        return "acompanhamento"
    return "prato"


CAMPOS = ["id", "livro", "pagina_pdf", "nome", "secao", "regiao", "tipo", "rendimento", "porcao",
          "ingredientes", "preparo", "observacoes", "kcal_porcao", "carboidrato_g_porcao",
          "proteina_g_porcao", "lipidios_g_porcao", "fibra_g_porcao"]
NUT_COL = {"Valor energético": "kcal_porcao", "Carboidratos": "carboidrato_g_porcao",
           "Proteínas": "proteina_g_porcao", "Gorduras totais": "lipidios_g_porcao",
           "Fibra alimentar": "fibra_g_porcao"}


def main(ncflv_pdf, prs_pdf):
    receitas = extrair_ncflv(ncflv_pdf) + extrair_prs(prs_pdf)
    linhas = []
    for k, r in enumerate(receitas, start=1):
        ing = [f"[{s}] {t}" if s else t for s, t in r["ingredientes"]]
        linha = {"id": f"txt{k:03d}", "livro": r["livro"], "pagina_pdf": r["pagina"], "nome": r["nome"],
                 "secao": r["secao"], "regiao": r["regiao"], "tipo": tipo(r), "rendimento": r["rendimento"],
                 "porcao": r["porcao"], "ingredientes": " | ".join(ing),
                 "preparo": "\n".join(r["preparo"]), "observacoes": r["observacoes"]}
        for nome, col in NUT_COL.items():
            linha[col] = r["nutricao"].get(nome, "")
        linhas.append(linha)
    with open(SAIDA, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS, lineterminator="\n")
        w.writeheader()
        w.writerows(linhas)
    sem_preparo = [l["nome"] for l in linhas if not l["preparo"]]
    print(f"{len(linhas)} receitas -> {SAIDA.relative_to(RAIZ)}")
    print("por livro:", dict(Counter(l["livro"] for l in linhas)))
    print("por tipo:", dict(Counter(l["tipo"] for l in linhas)))
    if sem_preparo:
        print("SEM modo de preparo (conferir):", sem_preparo)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])

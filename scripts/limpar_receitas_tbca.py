"""
Tira as RECEITAS (pratos com vários ingredientes) da TBCA, para o mapa SOM trabalhar só com alimentos.

    python scripts/limpar_receitas_tbca.py      # mostra quantos saem e grava kb/som/tbca_receitas_removidas.csv

A função eh_receita() é usada também por preparar_tbca_som.py (monta a base do mapa) e por
ligar_ingredientes_tbca.py (liga os ingredientes do app), para as três etapas usarem a mesma regra.

Uma descrição é RECEITA quando (a primeira regra que bater vira o "motivo"):
  1. lista de ingredientes: a TBCA escreve receitas como "Nome, c/ sal, (ingrediente, ingrediente, ...)";
  2. nome de prato: salada, sopa, omelete, torta, bolo, moqueca, risoto, lasanha, papa de..., farofa...;
  3. prato "com": "Arroz com lentilha", "Bolo de batata doce com frango";
  4. alimento misturado com outro: "c/ batata", "c/ molho", "c/ legumes", "c/ recheio", "ao molho"...
     ou ensopado/recheado (temperos simples continuam sendo o alimento: "c/ óleo, cebola e alho", "c/ sal",
     "c/ casca", "c/ manteiga"; produtos de um item só também: leite c/ chocolate, iogurte c/ frutas, macarrão c/ ovos);
  5. classe "Fast food".
Ficam: alimentos crus e preparados de forma simples (cozido, grelhado, frito, refogado, à milanesa),
industrializados de um produto só (biscoito, iogurte, gelatina em pó) e ingredientes (farinha, óleo, açúcar).
"""
import re
import unicodedata
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
PLANILHA = RAIZ / "fontes" / "TBCA_dados_modelo.xlsx"
RELATORIO = RAIZ / "kb" / "som" / "tbca_receitas_removidas.csv"

LISTA_DE_INGREDIENTES = r",\s*\("
PRATOS = (r"^(salada|sopa|caldo(?!, [^,]*, tablete)|creme de (?!leite)|omelete|torta|bolo|pudim|moqueca|risoto|lasanha|pizza|sanduiche|misto|papa de|"
          r"vitamina|mousse|strogonoff|estrogonofe|escondidinho|feijoada|baiao|prato de comida|panqueca|quiche|empada|"
          r"empadinha|pastel|coxinha|esfiha|kibe|quibe|croquete|bobo|vatapa|acaraje|abara|caruru|tacaca|manicoba|"
          r"galinhada|arroz carreteiro|arroz doce|macarronada|nhoque|farofa|tutu|virado|mexido|fricasse|picadinho|"
          r"ensopado|cozido de|guisado|buchada|sarapatel|rabada|dobradinha|carne de panela|paella|yakisoba|sushi|temaki|"
          r"hamburguer|cachorro|brigadeiro|beijinho|quindim|manjar|pave|cocada|curau|pamonha|mingau|crepioca|espeto|"
          r"cestinha|casquinha|bolinho|risole|pasta de|tropeiro|pirao|quibebe|geladinho|sacole|suffle|sufle|charuto|mussaka|atolado|"
          r"molho (tartaro|branco|bechamel|vinagrete|caseiro|pesto|bolonhesa)|molho, (mostarda|caseiro)|vinagrete)")
PRATO_COM = r"^[^,]* com "
MISTURA = (r"\bao molho\b|\bensopad|rechead[oa] -|\bc/ ?(brocolis|batata|legume|vegeta|carne|frango|peixe|camarao|atum|sardinha|presunto|bacon|"
           r"calabresa|linguica|ovo|queijo|requeijao|tomate|cenoura|ervilha|milho|feijao|lentilha|grao|arroz|macarrao|massa|"
           r"molho|creme|recheio|cobertura|abobora|abobrinha|berinjela|espinafre|couve|repolho|mandioca|aipim|inhame|"
           r"pequi|pimentao|quiabo|maxixe|jilo|chuchu|vagem|palmito|cogumelo|champignon|azeitona|uva passa|frutas|banana|maca|morango|"
           r"leite|iogurte|aveia|granola|chocolate|doce de leite|leite condensado|coco|amendoim|castanha|nozes)")
# produtos de um item só que a TBCA escreve com "c/": continuam sendo alimentos
NAO_E_MISTURA = (r"^macarrao, trigo(, \w+)?, c/ ovos|^leite, vaca, c/ ?chocolate|^queijo, requeijao, c/ queijo|"
                 r"^iogurte, [^,]*, c/ (frutas|polpa)")


def sem_acento(t):
    return "".join(c for c in unicodedata.normalize("NFKD", str(t).lower()) if not unicodedata.combining(c))


def eh_receita(descricao, classe=""):
    """Devolve o motivo (texto) se a descrição for de uma receita; None se for um alimento."""
    n = sem_acento(descricao)
    if re.search(LISTA_DE_INGREDIENTES, n):
        return "lista de ingredientes"
    if re.match(PRATOS, n):
        return "nome de prato"
    if re.match(PRATO_COM, n):
        return "prato 'com'"
    if re.search(MISTURA, re.sub(NAO_E_MISTURA, "", n)):
        return "alimento misturado com outro"
    if classe == "Fast food":
        return "fast food"
    return None


def main():
    tb = pd.read_excel(PLANILHA, sheet_name="nutrientes_limpos")[["codigo", "descricao", "classe"]]
    tb["motivo"] = [eh_receita(d, c) for d, c in zip(tb.descricao, tb.classe)]
    fora = tb[tb.motivo.notna()]
    RELATORIO.parent.mkdir(parents=True, exist_ok=True)
    fora.to_csv(RELATORIO, index=False)
    print(f"TBCA: {len(tb)} itens -> {len(tb) - len(fora)} alimentos ficam, {len(fora)} receitas saem")
    print(fora.motivo.value_counts().to_string())
    print(f"lista do que saiu (com o motivo): {RELATORIO.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()

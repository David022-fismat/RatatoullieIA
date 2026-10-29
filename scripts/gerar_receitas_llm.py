"""
Gera receitas com o LLM para as LACUNAS da base, valida com o Avaliador e grava para curadoria.

    python scripts/gerar_receitas_llm.py                      # chama o LLM (precisa de ANTHROPIC_API_KEY)
    python scripts/gerar_receitas_llm.py --de-arquivo X.json  # valida respostas já geradas (sem API)

Saídas:
  fontes/receitas_llm.csv            aprovadas pelo Avaliador, com revisado_pelo_grupo=nao
  fontes/receitas_llm_rejeitadas.csv rejeitadas, com os motivos (para melhorar o prompt)
Depois: revise as receitas, troque para revisado_pelo_grupo=sim e rode scripts/construir_base.py.
"""
import csv
import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from agents.agentes import Guardiao, Perfil, carregar_base  # noqa: E402
from agents.avaliador import Avaliador  # noqa: E402
from agents.montador import Montador, llm_anthropic  # noqa: E402

LACUNAS = [   # o que falta na base -> restrições/tempo que a receita precisa respeitar
    {"lacuna": "rápida para quem mora sozinho (1 porção, até 20 min)", "porcoes": 1, "tempo": 20, "restricoes": []},
    {"lacuna": "vegetariana com leguminosa", "porcoes": 2, "tempo": 50, "restricoes": ["vegetariano"]},
    {"lacuna": "marmita para a semana que congela bem (4 porções)", "porcoes": 4, "tempo": 50, "restricoes": []},
    {"lacuna": "baixo custo", "porcoes": 2, "tempo": 40, "restricoes": []},
    {"lacuna": "sem lactose e sem glúten", "porcoes": 2, "tempo": 45, "restricoes": ["sem_lactose", "celiaco"]},
    {"lacuna": "regional nordestina do dia a dia", "porcoes": 2, "tempo": 45, "restricoes": []},
]
ARQ_OK, ARQ_REJ = RAIZ / "fontes" / "receitas_llm.csv", RAIZ / "fontes" / "receitas_llm_rejeitadas.csv"


def perfil_da_lacuna(l):
    return Perfil(restricoes=l["restricoes"], tempo_max_min=l["tempo"], pessoas=l["porcoes"])


def gerar_com_llm(montador, l, n=3):
    feedback = {"motivos": [], "rejeitadas": set(), "aprovadas": set()}
    prompt = montador.montar_prompt(perfil_da_lacuna(l), {}, feedback, n)
    prompt += f"\n\nLACUNA A COBRIR: receitas do tipo \"{l['lacuna']}\". Inclua o campo \"preparo\"."
    texto = montador.llm(prompt)
    return [{**r, "lacuna": l["lacuna"]} for r in json.loads(texto[texto.index("["): texto.rindex("]") + 1])]


def main():
    ing, rec, restr = carregar_base()
    avaliador = Avaliador(ing, restr)
    if "--de-arquivo" in sys.argv:
        propostas = json.loads(Path(sys.argv[sys.argv.index("--de-arquivo") + 1]).read_text(encoding="utf-8"))
    else:
        montador = Montador(ing, rec, Guardiao(restr), llm=llm_anthropic)
        propostas = [r for l in LACUNAS for r in gerar_com_llm(montador, l)]

    ja_existem = set()
    if ARQ_OK.exists():
        with open(ARQ_OK, encoding="utf-8") as f:
            ja_existem = {r["receita"] for r in csv.DictReader(f, delimiter=";")}
    lacuna_por_nome = {l["lacuna"]: l for l in LACUNAS}
    novas_ok, rejeitadas = [], []
    for r in propostas:
        l = lacuna_por_nome[r["lacuna"]]
        res = avaliador.avaliar(r, perfil_da_lacuna(l), estoque={})
        if not res.aprovada:
            rejeitadas.append({"receita": r["nome"], "lacuna": r["lacuna"], "motivos": " | ".join(res.motivos)})
        elif r["nome"] not in ja_existem:
            for i in r["ingredientes"]:
                novas_ok.append({"receita": r["nome"], "lacuna": r["lacuna"], "regiao": r.get("regiao", "Brasil"),
                                 "porcoes": r["porcoes"], "tempo_min": r["tempo_min"],
                                 "revisado_pelo_grupo": "nao", "ingrediente": i["id"], "gramas": i["gramas"],
                                 "preparo": r.get("preparo", "")})
    campos = ["receita", "lacuna", "regiao", "porcoes", "tempo_min", "revisado_pelo_grupo",
              "ingrediente", "gramas", "preparo"]
    novo = not ARQ_OK.exists()
    with open(ARQ_OK, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campos, delimiter=";")
        if novo:
            w.writeheader()
        w.writerows(novas_ok)
    with open(ARQ_REJ, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["receita", "lacuna", "motivos"], delimiter=";")
        w.writeheader()
        w.writerows(rejeitadas)
    n_ok = len({x["receita"] for x in novas_ok})
    print(f"{len(propostas)} propostas -> {n_ok} aprovadas pelo Avaliador, {len(rejeitadas)} rejeitadas")
    for x in rejeitadas:
        print(f"  rejeitada: {x['receita']}: {x['motivos']}")


if __name__ == "__main__":
    main()

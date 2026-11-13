import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
"""
Testa o Substituidor (mapa SOM da TBCA) direto, sem LLM.

    python demos/demo_substituicao.py                  # exemplos prontos
    python demos/demo_substituicao.py abobrinha        # um alimento qualquer
    python demos/demo_substituicao.py carne --vegetariano --knn

Para ver o Orquestrador DECIDINDO chamar a troca: python demos/demo_orquestrador.py (ou --llm, com chave).
"""
from agents.substituidor import Substituidor


def mostrar(r):
    if "erro" in r:
        print("  ", r["erro"]); return
    p = r["por_100g"]
    print(f"{r['alimento']}  [{r['grupo']}]  gaveta {r['gaveta_no_mapa']}  "
          f"({p['kcal']} kcal, {p['proteina_g']} g proteína /100 g)  — {r['metodo']}")
    for k, x in enumerate(r["substitutos"], 1):
        q = x["por_100g"]
        base = f"  | na base do app: {', '.join(x['na_base_do_app'])}" if x["na_base_do_app"] else ""
        print(f"   {k}. {x['nome'][:48]:48s} {x['motivo']:45s} {q['kcal']:4d} kcal {q['proteina_g']:5.1f} g prot{base}")
    print()


if __name__ == "__main__":
    s = Substituidor()
    print(f"Mapa SOM {s.lado}x{s.lado}: erro de quantização {s.qe:.3f}, erro topográfico {s.te:.3f}\n")
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    restr = [r for r in ("vegetariano", "sem_lactose", "celiaco", "alergia_ovo", "sem_carne_vermelha")
             if f"--{r}" in sys.argv]
    metodo = "knn" if "--knn" in sys.argv else "som"
    if args:
        mostrar(s.substituir(" ".join(args), n=6, restricoes=restr, metodo=metodo))
    else:
        mostrar(s.substituir("frango", id_app="frango"))
        mostrar(s.substituir("carne", id_app="carne_bovina", restricoes=["vegetariano"]))
        mostrar(s.substituir("arroz", id_app="arroz"))
        mostrar(s.substituir("abobrinha"))
        mostrar(s.substituir("banana"))

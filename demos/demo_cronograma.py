"""
Demo do cronograma por ingredientes: metas DRI -> Montador -> Avaliador -> 3 opções por refeição.

Antes, suba a API DRI de um destes jeitos (os dois respondem em http://localhost:3001):
    npx @mockoon/cli start --data mocks/dri.json     # o mock (metas fixas de exemplo)
    python -m servicos.api_dri                       # a calculadora de verdade
Sem nenhuma das duas no ar, o cliente calcula as metas localmente e avisa.

    python demos/demo_cronograma.py
    python demos/demo_cronograma.py --regiao Sul --restricoes vegetariano --nao-gosta tomate
    python demos/demo_cronograma.py --sexo M --idade 40 --altura 180 --peso 85 --atividade ativo
    python demos/demo_cronograma.py --aprender      # simula 20 almoços e mostra o que o bandit aprendeu
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agents.cliente_dri import PerfilRecusado      # noqa: E402
from agents.cronograma import Cronograma           # noqa: E402


def mostrar_dia(dia):
    print(f"\nMetas: {dia['fonte_metas']}  |  energia do dia: {dia['energia_dia_kcal']} kcal")
    for aviso in dia["avisos"]:
        print(f"  aviso: {aviso}")
    for r in dia["refeicoes"].values():
        m, a = r["metas"], r["avaliacao"]
        print(f"\n=== {r['refeicao']}  (meta: {m['energia_kcal']} kcal, proteína ≥ {m['proteina_g']} g, "
              f"fibra {m['fibra_g']} g, sódio ≤ {m['sodio_mg_max']} mg)")
        print(f"    {a['combinacoes']} combinações, {a['vetadas']} vetadas, {a.get('saudaveis', 0)} na metade mais saudável")
        if not r["opcoes"]:
            print("    nenhuma opção passou na trava: reveja as restrições")
        for k, o in enumerate(r["opcoes"], 1):
            print(f"  Opção {k}  (bem-estar {o['bem_estar']:.2f})")
            for i in o["itens"]:
                print(f"     {i['grupo']:<12} {i['gramas']:>5.0f} g  {i['alimento'][:70]}")
            t, p = o["totais"], o["percentual_da_meta"]
            print(f"     = {t['energia_kcal']:.0f} kcal ({p['energia']}% da meta) · proteína {t['proteina_g']:.0f} g "
                  f"({p['proteina']}%) · fibra {t['fibra_g']:.0f} g · sódio {t['sodio_mg']:.0f} mg")


def simular_aprendizado(c, dias=20):
    """Pessoa que prefere peixe e frango e evita fritura: escolhe a opção que mais combina com isso."""
    gosto = {"proteina:peixe": 2, "proteina:aves": 1, "frito": -1.5}
    print(f"\n--- {dias} almoços com uma pessoa que prefere peixe e frango e evita fritura ---")
    for _ in range(dias):
        c.opcoes("almoco")
        ops = c.mostradas["almoco"]
        pontos = []
        for itens, alimentos in zip(ops.itens, ops.itens):
            p = sum(gosto.get(f"proteina:{i['subtipo']}", 0) for i in itens if i["grupo"] == "proteina")
            p += gosto["frito"] * any("frit" in i["alimento"].lower() for i in alimentos)
            pontos.append(p)
        c.escolher("almoco", max(range(len(pontos)), key=pontos.__getitem__))
    gosta, evita = c.avaliador.explicar("almoco", 4)
    print("o bandit aprendeu que a pessoa tende a escolher:", ", ".join(f"{k} ({v:+.2f})" for k, v in gosta.items()))
    print("e tende a evitar:", ", ".join(f"{k} ({v:+.2f})" for k, v in evita.items()))
    print("\nAlmoço depois do aprendizado:")
    mostrar_dia({"fonte_metas": c.metas["fonte"], "energia_dia_kcal": c.metas["dia"]["energia_kcal"], "avisos": [],
                 "refeicoes": {"almoco": c.opcoes("almoco")}})


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--sexo", default="F")
    p.add_argument("--idade", type=float, default=30)
    p.add_argument("--altura", type=float, default=163)
    p.add_argument("--peso", type=float, default=62)
    p.add_argument("--atividade", default="pouco_ativo", choices=["inativo", "pouco_ativo", "ativo", "muito_ativo"])
    p.add_argument("--regiao", default="Nordeste")
    p.add_argument("--restricoes", nargs="*", default=[])
    p.add_argument("--nao-gosta", nargs="*", default=[])
    p.add_argument("--local", action="store_true", help="não chama a API: calcula as metas direto")
    p.add_argument("--aprender", action="store_true")
    a = p.parse_args()
    dados = {"sexo": a.sexo, "idade": a.idade, "altura_cm": a.altura, "peso_kg": a.peso, "atividade": a.atividade}
    try:
        c = Cronograma(dados, restricoes=a.restricoes, nao_gosta=a.nao_gosta, regiao=a.regiao, usar_api=not a.local)
    except PerfilRecusado as e:
        sys.exit(f"Não dá para montar o cronograma: {e}")
    mostrar_dia(c.dia())
    if a.aprender:
        simular_aprendizado(c)


if __name__ == "__main__":
    main()

"""
Porta de entrada do agente: pergunta o perfil e o estoque, monta o cardápio e aprende com o retorno.

    python agente.py           # usa o Montador com a base de receitas (sem LLM)
    python agente.py --llm     # usa o Montador com LLM (precisa de ANTHROPIC_API_KEY)
    python agente.py --novo    # ignora o perfil salvo e pergunta tudo de novo

O perfil fica salvo em perfil.json, e os pesos aprendidos também, para a próxima vez.
"""
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from agentes import Guardiao, LeitorDeNota, Perfil, carregar_base
from avaliador import Avaliador
from montador import Montador, llm_anthropic
from planejamento import aprender_com_feedback, planejar

ARQ_PERFIL = Path(__file__).parent / "perfil.json"
RESTRICOES = ["vegetariano", "sem_lactose", "celiaco", "alergia_ovo", "sem_carne_vermelha"]
GRAMAS_PADRAO = 500          # quando a pessoa só diz "tenho ovo", sem quantidade


def perguntar(texto, padrao=""):
    r = input(f"{texto}" + (f" [{padrao}]" if padrao != "" else "") + ": ").strip()
    return r or str(padrao)


def ler_ingredientes(texto, leitor):
    """'ovo 600, tomate, abobrinha 300g' -> ({'ovo': 600, 'tomate': 500, ...}, [não reconhecidos])"""
    achados, duvidas = {}, []
    for parte in filter(None, (p.strip() for p in texto.split(","))):
        palavras = parte.split()
        ultimo = palavras[-1].lower().removesuffix("g")
        if ultimo.isdigit() and len(palavras) > 1:          # "abobrinha 300g" ou "ovo 600"
            gramas, nome = int(ultimo), " ".join(palavras[:-1])
        else:
            gramas, nome = GRAMAS_PADRAO, parte
        iid, conf = leitor.classificar(nome)
        if iid and conf >= leitor.LIMIAR:
            achados[iid] = achados.get(iid, 0) + gramas
        else:
            duvidas.append(nome)
    return achados, duvidas


def montar_perfil(leitor, ing):
    print("\n--- Seu perfil ---")
    print("Restrições disponíveis:")
    for i, r in enumerate(RESTRICOES, 1):
        print(f"  {i}. {r}")
    escolha = perguntar("Números das suas restrições, separados por vírgula (Enter = nenhuma)")
    restricoes = [RESTRICOES[int(x) - 1] for x in escolha.replace(" ", "").split(",")
                  if x.isdigit() and 1 <= int(x) <= len(RESTRICOES)]
    pessoas = int(perguntar("Quantas pessoas comem", 2))
    tempo = int(perguntar("Tempo máximo para cozinhar, em minutos", 40))
    regiao = perguntar("Região", "Brasil")
    gosta, _ = ler_ingredientes(perguntar("Ingredientes que você gosta (ex.: ovo, mandioca)"), leitor)
    nao_gosta, _ = ler_ingredientes(perguntar("Ingredientes que você NÃO gosta"), leitor)
    return Perfil(restricoes=restricoes, pessoas=pessoas, tempo_max_min=tempo, regiao=regiao,
                  gosta=list(gosta), nao_gosta=list(nao_gosta))


def carregar_perfil(leitor, ing):
    if ARQ_PERFIL.exists() and "--novo" not in sys.argv:
        p = Perfil(**json.loads(ARQ_PERFIL.read_text(encoding="utf-8")))
        print(f"\nPerfil salvo: restrições={p.restricoes or 'nenhuma'}, {p.pessoas} pessoa(s), "
              f"até {p.tempo_max_min} min, gosta de {p.gosta or '-'}")
        if perguntar("Usar esse perfil? (s/n)", "s").lower().startswith("s"):
            return p
    return montar_perfil(leitor, ing)


def salvar_perfil(p):
    p.pesos = {k: round(v, 3) for k, v in p.pesos.items()}
    ARQ_PERFIL.write_text(json.dumps(asdict(p), ensure_ascii=False, indent=1), encoding="utf-8")


def mostrar(res, ing, avaliador, perfil):
    print(f"\n{'=' * 70}\nCARDÁPIO ({res['status']})\n{'=' * 70}")
    for h in res["historico"]:
        extra = f" | rejeitadas: {'; '.join(h['motivos'])}" if h["motivos"] else ""
        print(f"(rodada {h['rodada']}: {h['aprovadas']} aprovadas de {h['propostas']}{extra})")
    for k, x in enumerate(res["cardapio"], 1):
        r = x.receita
        fator = perfil.pessoas / max(1, r["porcoes"])          # ajusta para o número de pessoas
        nut = x.detalhes["nutrientes_por_pessoa"]
        print(f"\n{k}. {r['nome']}  ({r['tempo_min']} min, nota {x.nota:.2f})")
        print(f"   Por quê: {x.explicacao}")
        itens = ", ".join(f"{ing[i['id']]['nome']} {i['gramas'] * fator:.0f} g" for i in r["ingredientes"])
        print(f"   Para {perfil.pessoas} pessoa(s): {itens}")
        print(f"   Por pessoa: {nut['kcal']:.0f} kcal, {nut['proteina_g']:.0f} g de proteína, "
              f"{nut['fibra_g']:.0f} g de fibra")


def main():
    ing, rec, restr = carregar_base()
    leitor, guardiao, avaliador = LeitorDeNota(ing), Guardiao(restr), Avaliador(ing, restr)

    perfil = carregar_perfil(leitor, ing)
    salvar_perfil(perfil)

    print("\n--- O que você tem em casa ---")
    texto = perguntar("Ingredientes e gramas (ex.: ovo 600, tomate, abobrinha 300g)")
    estoque, duvidas = ler_ingredientes(texto, leitor)
    if duvidas:
        print(f"Não reconheci: {', '.join(duvidas)} (ficaram de fora)")
    print("Entendi:", ", ".join(f"{ing[i]['nome']} {g} g" for i, g in estoque.items()) or "nada")
    n = int(perguntar("Quantas refeições planejar", 5))

    usar_llm = "--llm" in sys.argv
    if usar_llm and not os.getenv("ANTHROPIC_API_KEY"):
        print("Sem ANTHROPIC_API_KEY: usando a base de receitas.")
        usar_llm = False
    montador = Montador(ing, rec, guardiao, llm=llm_anthropic if usar_llm else None)

    res = planejar(montador, avaliador, perfil, estoque, n=n)
    mostrar(res, ing, avaliador, perfil)
    if not res["cardapio"]:
        print("\nNenhuma receita passou. Tente aumentar o tempo máximo ou tirar uma restrição.")
        return

    print("\n--- Retorno (o agente aprende com isso) ---")
    feitas_txt = perguntar("Quais você faria? Números separados por vírgula (Enter = pular)")
    if feitas_txt:
        nomes = [x.receita["nome"] for x in res["cardapio"]]
        feitas = [nomes[int(k) - 1] for k in feitas_txt.replace(" ", "").split(",")
                  if k.isdigit() and 1 <= int(k) <= len(nomes)]
        chaves = ("natural", "tem_vegetal", "gosto", "rapidez", "usa_estoque")
        caracts = {x.receita["nome"]: {k: x.detalhes[k] for k in chaves} for x in res["cardapio"]}
        antes = dict(perfil.pesos)
        aprender_com_feedback(perfil, caracts, feitas)
        salvar_perfil(perfil)
        mudou = {k: f"{antes.get(k, 1.0):.2f} → {v:.2f}" for k, v in perfil.pesos.items()
                 if abs(v - antes.get(k, 1.0)) > 0.005}
        print("Pesos atualizados:", mudou or "sem mudança")


if __name__ == "__main__":
    main()

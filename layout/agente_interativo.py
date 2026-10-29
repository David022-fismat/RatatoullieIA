"""
Porta de entrada do agente: pergunta o perfil e o estoque, monta o cardápio e aprende com o retorno.

    python layout/agente_interativo.py           # usa o Montador com a base de receitas (sem LLM)
    python layout/agente_interativo.py --llm     # usa o Montador com LLM (chave do Gemini, Groq ou Anthropic)
    python layout/agente_interativo.py --novo    # ignora o perfil salvo e pergunta tudo de novo
    python layout/agente_interativo.py --esquecer  # apaga a memória da semana (o que já foi sugerido)
    python layout/agente_interativo.py --chat    # conversa livre com o Orquestrador, que decide quais agentes chamar
                               # (chave do Gemini, Groq ou Anthropic; veja agents/provedores.py)

O perfil fica salvo em perfil.json, e os pesos aprendidos também, para a próxima vez.
"""
import json
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # pasta principal do projeto

from agents.agentes import (ARQ_PERFIL, RESTRICOES, Guardiao, LeitorDeNota, Perfil,  # noqa: E402
                            carregar_base, reconhecer, salvar_perfil)
from agents.avaliador import Avaliador  # noqa: E402
from agents.memoria import PESO_NOVIDADE, MemoriaSemana  # noqa: E402
from agents.montador import Montador  # noqa: E402
from agents.planejamento import aprender_com_feedback, planejar  # noqa: E402

GRAMAS_PADRAO = 500          # quando a pessoa só diz "tenho ovo", sem quantidade


def perguntar(texto, padrao=""):
    r = input(f"{texto}" + (f" [{padrao}]" if padrao != "" else "") + ": ").strip()
    return r or str(padrao)


def perguntar_numero(texto, padrao):
    while True:
        r = perguntar(texto, padrao)
        if r.isdigit() and int(r) > 0:
            return int(r)
        print("  Digite um número inteiro, por exemplo 2.")


leitor_nomes = {}


def ler_ingredientes(texto, leitor):
    """'ovo 600, tomate, abobrinha 300g' -> ({'ovo': 600, 'tomate': 500, ...}, [não reconhecidos])"""
    achados, duvidas = {}, []
    for parte in filter(None, (p.strip() for p in texto.split(","))):
        palavras = parte.split()
        ultimo = palavras[-1].lower()
        if ultimo.endswith("g"):
            ultimo = ultimo[:-1]
        if ultimo.isdigit() and len(palavras) > 1:          # "abobrinha 300g" ou "ovo 600"
            gramas, nome = int(ultimo), " ".join(palavras[:-1])
        else:
            gramas, nome = GRAMAS_PADRAO, parte
        iid, exato = reconhecer(nome, leitor)
        if iid:
            achados[iid] = achados.get(iid, 0) + gramas
            if not exato:
                print(f"  (entendi '{nome}' como {leitor_nomes[iid]})")
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
    pessoas = perguntar_numero("Quantas pessoas comem", 2)
    tempo = perguntar_numero("Tempo máximo para cozinhar, em minutos", 40)
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


def mostrar(res, ing, perfil, estoque):
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
        falta = [ing[i["id"]]["nome"] for i in r["ingredientes"] if estoque.get(i["id"], 0) < i["gramas"] * fator]
        print(f"   Falta comprar: {', '.join(falta) if falta else 'nada, você tem tudo'}")
        print(f"   Por pessoa: {nut['kcal']:.0f} kcal, {nut['proteina_g']:.0f} g de proteína, "
              f"{nut['fibra_g']:.0f} g de fibra")


def chat():
    from agents.provedores import criar_cliente, funcao_texto, provedor_disponivel
    provedor = provedor_disponivel()
    if provedor is None:
        print("O modo conversa precisa da chave de um LLM. Opções grátis:")
        print("  Gemini: crie em aistudio.google.com/apikey e rode  export GEMINI_API_KEY=sua-chave")
        print("  Groq:   crie em console.groq.com/keys e rode     export GROQ_API_KEY=sua-chave")
        print("Para ver o Orquestrador decidindo sem chave: python demo_orquestrador.py")
        return
    if provedor == "anthropic":
        try:
            import anthropic  # noqa: F401
        except ImportError:
            print("Instale o SDK: pip install anthropic")
            return
    from agents.orquestrador import Orquestrador, conversar
    if not ARQ_PERFIL.exists() or "--novo" in sys.argv:
        ing, _, _ = carregar_base()
        leitor_nomes.update({i: x["nome"] for i, x in ing.items()})
        salvar_perfil(montar_perfil(LeitorDeNota(ing), ing))
    cliente, modelo = criar_cliente(provedor)
    print(f"(LLM: {provedor}, modelo {modelo})")
    llm_montador = funcao_texto(provedor) if "--llm" in sys.argv else None
    conversar(Orquestrador(cliente=cliente, modelo=modelo, llm_montador=llm_montador))


def main():
    if "--chat" in sys.argv:
        return chat()
    ing, rec, restr = carregar_base()
    memoria = MemoriaSemana(ing)                       # o que já foi sugerido nos últimos 7 dias
    leitor, guardiao = LeitorDeNota(ing), Guardiao(restr)
    avaliador = Avaliador(ing, restr, memoria=memoria)
    leitor_nomes.update({i: x["nome"] for i, x in ing.items()})
    if "--esquecer" in sys.argv:
        memoria.limpar()
        print("Memória da semana apagada.")

    perfil = carregar_perfil(leitor, ing)
    salvar_perfil(perfil)

    print("\n--- O que você tem em casa ---")
    texto = perguntar("Ingredientes e gramas (ex.: ovo 600, tomate, abobrinha 300g)")
    estoque, duvidas = ler_ingredientes(texto, leitor)
    if perguntar("Tem o básico de despensa: óleo, alho, cebola e arroz? (s/n)", "s").lower().startswith("s"):
        for i in ("oleo", "alho", "cebola", "arroz"):
            estoque.setdefault(i, 1000)
    if duvidas:
        print(f"Não reconheci: {', '.join(duvidas)} (ficaram de fora)")
    print("Entendi:", ", ".join(f"{ing[i]['nome']} {g} g" for i, g in estoque.items()) or "nada")
    n = perguntar_numero("Quantas refeições planejar", 5)

    llm = None
    if "--llm" in sys.argv:
        from agents.provedores import funcao_texto, provedor_disponivel
        provedor = provedor_disponivel()
        if provedor:
            llm = funcao_texto(provedor)
        else:
            print("Sem chave de LLM (GEMINI_API_KEY, GROQ_API_KEY ou ANTHROPIC_API_KEY): usando a base.")
    montador = Montador(ing, rec, guardiao, llm=llm)

    res = planejar(montador, avaliador, perfil, estoque, n=n)
    mostrar(res, ing, perfil, estoque)
    memoria.registrar([x.receita for x in res["cardapio"]])
    if not res["cardapio"]:
        print("\nNenhuma receita passou. Tente aumentar o tempo máximo ou tirar uma restrição.")
        return

    print("\n--- Retorno (o agente aprende com isso) ---")
    feitas_txt = perguntar("Quais você faria? Números separados por vírgula (Enter = pular)")
    if feitas_txt:
        nomes = [x.receita["nome"] for x in res["cardapio"]]
        feitas = [nomes[int(k) - 1] for k in feitas_txt.replace(" ", "").split(",")
                  if k.isdigit() and 1 <= int(k) <= len(nomes)]
        chaves = ("natural", "tem_vegetal", "gosto", "rapidez", "usa_estoque", "tem_em_casa", "novidade")
        caracts = {x.receita["nome"]: {k: x.detalhes[k] for k in chaves if k in x.detalhes}
                   for x in res["cardapio"]}
        antes = {"novidade": PESO_NOVIDADE, **perfil.pesos}
        aprender_com_feedback(perfil, caracts, feitas)
        salvar_perfil(perfil)
        mudou = {k: f"{antes.get(k, 1.0):.2f} → {v:.2f}" for k, v in perfil.pesos.items()
                 if abs(v - antes.get(k, 1.0)) > 0.005}
        print("Pesos atualizados:", mudou or "sem mudança")


if __name__ == "__main__":
    main()

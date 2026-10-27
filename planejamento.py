"""
Laço entre Montador e Avaliador.

  rodada 1: Montador propõe -> Avaliador aprova/rejeita -> motivos acumulam
  rodada 2: Montador recebe TODOS os motivos e propõe só o que falta
  ...
  para quando tem receitas suficientes ou chega em MAX_RODADAS.
"""
import json
from pathlib import Path

ARQ_APROVADAS_LLM = Path(__file__).parent / "kb" / "aprovadas_llm.jsonl"


def planejar(montador, avaliador, perfil, estoque, n=7, max_rodadas=3, salvar_aprovadas=True):
    feedback = {"motivos": [], "rejeitadas": set(), "aprovadas": set()}
    aprovadas, historico = [], []

    for rodada in range(1, max_rodadas + 1):
        faltam = n - len(aprovadas)
        propostas = montador.propor(perfil, estoque, feedback, n=faltam + 2)  # margem
        ok, motivos, todos = avaliador.avaliar_lote(propostas, perfil, estoque)

        for x in ok:
            if x.receita["nome"] not in feedback["aprovadas"]:
                aprovadas.append(x)
                feedback["aprovadas"].add(x.receita["nome"])
                if salvar_aprovadas and x.receita.get("origem") == "llm":   # alimenta a base
                    with open(ARQ_APROVADAS_LLM, "a", encoding="utf-8") as f:
                        f.write(json.dumps(x.receita, ensure_ascii=False) + "\n")
        for x in todos:
            if not x.aprovada:
                feedback["rejeitadas"].add(x.receita["nome"])
        feedback["motivos"] = sorted(set(feedback["motivos"]) | set(motivos))  # acumula

        historico.append({"rodada": rodada, "propostas": len(propostas),
                          "aprovadas": len(ok), "rejeitadas": len(todos) - len(ok),
                          "motivos": motivos})
        if len(aprovadas) >= n:
            break

    aprovadas.sort(key=lambda x: -x.nota)
    status = "completo" if len(aprovadas) >= n else f"faltaram {n - len(aprovadas)} receitas"
    return {"cardapio": aprovadas[:n], "status": status, "historico": historico,
            "log_montador": montador.log}


def aprender_com_feedback(perfil, caracteristicas, feitas, taxa=0.1, minimo=0.2, maximo=3.0):
    """Ajusta os pesos do perfil com o retorno da semana ("fiz" / "não fiz").

    caracteristicas: {nome_receita: {caracteristica: valor 0..1}} das receitas SUGERIDAS
    feitas: nomes das receitas que a pessoa fez

    Cada característica é comparada com a MÉDIA das sugestões. Assim só muda o peso do que
    realmente diferencia as receitas feitas das não feitas (ex.: quase toda receita é "in natura",
    então fazer uma receita in natura não diz nada sobre a pessoa).
    """
    if not caracteristicas:
        return
    chaves = next(iter(caracteristicas.values())).keys()
    media = {k: sum(c[k] for c in caracteristicas.values()) / len(caracteristicas) for k in chaves}
    for nome, c in caracteristicas.items():
        sinal = 1 if nome in feitas else -1
        for k in chaves:
            perfil.pesos[k] = min(maximo, max(minimo, perfil.pesos.get(k, 1.0) + taxa * sinal * (c[k] - media[k])))

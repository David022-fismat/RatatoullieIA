"""
Laço entre Montador e Avaliador.

  rodada 1: Montador propõe -> Avaliador aprova/rejeita -> motivos acumulam
  rodada 2: Montador recebe TODOS os motivos e propõe só o que falta
  ...
  para quando tem receitas suficientes ou chega em MAX_RODADAS.
"""
import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent      # pasta principal do projeto
ARQ_APROVADAS_LLM = RAIZ / "kb" / "aprovadas_llm.jsonl"


def planejar(montador, avaliador, perfil, estoque, n=7, max_rodadas=3, salvar_aprovadas=True):
    feedback = {"motivos": [], "rejeitadas": set(), "aprovadas": set()}
    memoria = getattr(avaliador, "memoria", None)
    if memoria is not None:                       # o Montador também vê o que já foi sugerido na semana
        feedback["recentes"] = memoria.recentes()
    aprovadas, historico = [], []

    for rodada in range(1, max_rodadas + 1):
        faltam = n - len(aprovadas)
        margem = faltam + 2 if memoria is None else 2 * faltam + 3     # com memória, mais opções
        propostas = montador.propor(perfil, estoque, feedback, n=margem)
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
    if memoria is not None:
        aprovadas = _variar(aprovadas, avaliador, perfil)
    status = "completo" if len(aprovadas) >= n else f"faltaram {n - len(aprovadas)} receitas"
    return {"cardapio": aprovadas[:n], "status": status, "historico": historico,
            "log_montador": montador.log}


def _variar(aprovadas, avaliador, perfil):
    """Escolhe as receitas uma a uma, descontando a semelhança com as já escolhidas no mesmo cardápio
    (evita dois cuscuz na mesma semana). Só roda quando o Avaliador tem memória."""
    from .memoria import PESO_NOVIDADE, semelhanca
    peso = perfil.pesos.get("novidade", PESO_NOVIDADE)
    restantes, escolhidas = list(aprovadas), []
    while restantes:
        def ajustada(x):
            sim = max((semelhanca(x.receita, e.receita, avaliador.ing) for e in escolhidas), default=0.0)
            return x.nota - peso * sim
        melhor = max(restantes, key=ajustada)
        escolhidas.append(melhor)
        restantes.remove(melhor)
    return escolhidas


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
    from .memoria import PESO_NOVIDADE
    chaves = next(iter(caracteristicas.values())).keys()
    media = {k: sum(c[k] for c in caracteristicas.values()) / len(caracteristicas) for k in chaves}
    for nome, c in caracteristicas.items():
        sinal = 1 if nome in feitas else -1
        for k in chaves:
            atual = perfil.pesos.get(k, PESO_NOVIDADE if k == "novidade" else 1.0)
            perfil.pesos[k] = min(maximo, max(minimo, atual + taxa * sinal * (c[k] - media[k])))

"""
Experimentos com os agentes Montador e Avaliador. Gera resultados/experimentos.json.

    python scripts/experimentos.py

E1 Cobertura: quantos pratos cada restrição deixa disponíveis, antes e depois das adaptações do Montador.
E2 Detecção: o Avaliador pega erros injetados de propósito em receitas (como um LLM erraria)?
E3 Laço de rodadas: com um "LLM" que erra p% das receitas, quantas rodadas até fechar o cardápio?
E4 Personalização: usuários simulados com gosto escondido; a taxa de aceitação sobe com o aprendizado?
E5 Nutrientes: kcal e proteína por pessoa de cada prato, por fonte da receita.
"""
import json
import random
import statistics
import sys
from copy import deepcopy
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from agents.agentes import Guardiao, Perfil, carregar_base  # noqa: E402
from agents.avaliador import Avaliador  # noqa: E402
from agents.montador import Montador  # noqa: E402
from agents.planejamento import aprender_com_feedback, planejar  # noqa: E402

random.seed(42)
ing, rec, restr = carregar_base()
guardiao, avaliador = Guardiao(restr), Avaliador(ing, restr)
montador_base = Montador(ing, rec, guardiao)
PRATOS = [r for r in rec.values() if r.get("tipo", "prato") == "prato"]
FONTE = {"r": "Grupo", "m": "Ministério da Saúde", "i": "IA (lacunas)"}


def como_json(r):
    return montador_base._receita_base_para_json(r)


# ---------------------------------------------------------------- E1
def e1_cobertura():
    casos = [[], ["vegetariano"], ["sem_lactose"], ["celiaco"], ["alergia_ovo"], ["sem_carne_vermelha"],
             ["vegetariano", "sem_lactose"], ["celiaco", "sem_lactose"]]
    saida = []
    for c in casos:
        p = Perfil(restricoes=c)
        proib = guardiao.proibidos(p)
        originais = sum(1 for r in PRATOS if not set(r["itens"]) & proib)
        com_adaptacao = sum(1 for r in PRATOS if montador_base._adaptar(r, p) is not None)
        saida.append({"perfil": " + ".join(c) or "sem restrição", "originais": originais,
                      "com_adaptacao": com_adaptacao, "total": len(PRATOS)})
    return saida


# ---------------------------------------------------------------- E2
TIPOS_ERRO = ["ingrediente proibido", "ingrediente inexistente", "porção absurda (×5)",
              "tempo acima do limite", "sem erro (controle)"]


def injetar(r, tipo, perfil):
    r = deepcopy(r)
    if tipo == "ingrediente proibido":
        proib = sorted(guardiao.proibidos(perfil))
        r["ingredientes"].append({"id": random.choice(proib), "gramas": 100})
    elif tipo == "ingrediente inexistente":
        r["ingredientes"].append({"id": random.choice(["quinoa", "tofu_defumado", "requeijao", "shimeji"]),
                                  "gramas": 100})
    elif tipo == "porção absurda (×5)":
        maior = max(r["ingredientes"], key=lambda i: i["gramas"])
        maior["gramas"] *= 5
    elif tipo == "tempo acima do limite":
        r["tempo_min"] = perfil.tempo_max_min + random.choice([10, 30, 90])
    return r


def e2_deteccao(n_por_tipo=300):
    saida = []
    for tipo in TIPOS_ERRO:
        pegos = 0
        for _ in range(n_por_tipo):
            p = Perfil(restricoes=[random.choice(["vegetariano", "sem_lactose", "celiaco", "alergia_ovo"])],
                       tempo_max_min=90)
            candidatas = [r for r in PRATOS if montador_base._adaptar(r, p) and r["tempo_min"] <= 90]
            base = random.choice(candidatas)
            itens, nome, _ = montador_base._adaptar(base, p)
            r = injetar(montador_base._receita_base_para_json(base, itens, nome), tipo, p)
            if not avaliador.avaliar(r, p, {}).aprovada:
                pegos += 1
        saida.append({"tipo": tipo, "rejeitadas_pct": round(100 * pegos / n_por_tipo, 1), "n": n_por_tipo})
    return saida


# ---------------------------------------------------------------- E3
class LLMQueErra:
    """Devolve receitas reais da base; cada uma vem com um erro com probabilidade p. Não aprende."""
    def __init__(self, p, perfil):
        self.p, self.perfil = p, perfil

    def __call__(self, prompt):
        ok = [r for r in PRATOS if montador_base._adaptar(r, self.perfil)
              and r["tempo_min"] <= self.perfil.tempo_max_min]
        saida = []
        for r in random.sample(ok, k=min(6, len(ok))):
            itens, nome, _ = montador_base._adaptar(r, self.perfil)
            j = montador_base._receita_base_para_json(r, itens, nome)
            j["nome"] += f" #{random.randint(0, 10**6)}"            # nomes únicos entre rodadas
            if random.random() < self.p:
                j = injetar(j, random.choice(TIPOS_ERRO[:4]), self.perfil)
            saida.append(j)
        return json.dumps(saida, ensure_ascii=False)


def e3_rodadas(taxas=(0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8), n=200):
    saida = []
    for p in taxas:
        rodadas, completos = [], 0
        for _ in range(n):
            perfil = Perfil(restricoes=[random.choice(["vegetariano", "sem_lactose", "celiaco"])],
                            tempo_max_min=60)
            m = Montador(ing, rec, guardiao, llm=LLMQueErra(p, perfil))
            res = planejar(m, avaliador, perfil, {}, n=5, max_rodadas=3, salvar_aprovadas=False)
            rodadas.append(len(res["historico"]))
            completos += res["status"] == "completo"
        saida.append({"taxa_erro_llm": p, "rodadas_media": round(statistics.mean(rodadas), 2),
                      "completos_pct": round(100 * completos / n, 1)})
    return saida


# ---------------------------------------------------------------- E4
ARQUETIPOS = {   # gosto escondido do usuário sobre as características que o Avaliador calcula
    "quer rapidez": {"rapidez": 2.0, "natural": 0.0, "tem_vegetal": 0.0},
    "quer comida in natura": {"rapidez": 0.0, "natural": 2.0, "tem_vegetal": 0.3},
    "quer verdura no prato": {"rapidez": 0.0, "natural": 0.3, "tem_vegetal": 2.0},
}


def e4_personalizacao(n_usuarios=60, semanas=12, sugestoes=5, taxa=0.1):
    def aceita(c, oculto, limiar):
        return sum(oculto.get(k, 0) * v for k, v in c.items()) >= limiar

    curvas = {m: [[] for _ in range(semanas)] for m in ("sem aprendizado", "regra simples", "regra centrada")}
    por_arq = {a: {m: [[] for _ in range(semanas)] for m in curvas} for a in ARQUETIPOS}
    for modo in curvas:
        random.seed(7)
        for u in range(n_usuarios):
            arq = list(ARQUETIPOS)[u % len(ARQUETIPOS)]
            oculto = ARQUETIPOS[arq]
            perfil = Perfil(tempo_max_min=120)
            perfil.pesos = {"natural": 1.0, "tem_vegetal": 1.0, "gosto": 1.0, "rapidez": 1.0, "usa_estoque": 1.0}
            caracts = {}
            for r in PRATOS:
                res = avaliador.avaliar(como_json(r), perfil, {})
                if res.aprovada:
                    caracts[r["nome"]] = {k: res.detalhes[k] for k in ("natural", "tem_vegetal", "rapidez")}
            utilidades = sorted(sum(oculto[k] * v for k, v in c.items()) for c in caracts.values())
            limiar = utilidades[int(0.8 * len(utilidades))]          # aceita só o top 20% para ele
            for s in range(semanas):
                nota = {n: sum(perfil.pesos[k] * v for k, v in c.items()) + random.gauss(0, 0.15)
                        for n, c in caracts.items()}
                top = sorted(nota, key=nota.get, reverse=True)[:sugestoes]
                feitas = [n for n in top if aceita(caracts[n], oculto, limiar)]
                curvas[modo][s].append(100 * len(feitas) / sugestoes)
                por_arq[arq][modo][s].append(100 * len(feitas) / sugestoes)
                if modo == "regra centrada":                        # planejamento.aprender_com_feedback
                    aprender_com_feedback(perfil, {n: caracts[n] for n in top}, feitas, taxa=taxa)
                elif modo == "regra simples":                       # mesma regra de agentes.aprender
                    for n in top:
                        sinal = 1 if n in feitas else -1
                        for k, v in caracts[n].items():
                            perfil.pesos[k] = min(3.0, max(0.2, perfil.pesos[k] + taxa * sinal * v))
    media = lambda v: [round(statistics.mean(x), 1) for x in v]  # noqa: E731
    return {"geral": {m: media(v) for m, v in curvas.items()},
            "por_arquetipo": {a: {m: media(v) for m, v in d.items()} for a, d in por_arq.items()}}


# ---------------------------------------------------------------- E5
def e5_nutrientes():
    saida = []
    for r in PRATOS:
        n = avaliador.nutrientes_por_pessoa(como_json(r))
        saida.append({"nome": r["nome"], "fonte": FONTE[r["id"][0]], "kcal": n["kcal"],
                      "proteina_g": n["proteina_g"], "fibra_g": n["fibra_g"]})
    return saida


if __name__ == "__main__":
    resultados = {"n_pratos": len(PRATOS), "e1_cobertura": e1_cobertura(), "e2_deteccao": e2_deteccao(),
                  "e3_rodadas": e3_rodadas(), "e4_personalizacao": e4_personalizacao(),
                  "e5_nutrientes": e5_nutrientes()}
    destino = RAIZ / "resultados"
    destino.mkdir(exist_ok=True)
    (destino / "experimentos.json").write_text(json.dumps(resultados, ensure_ascii=False, indent=1),
                                               encoding="utf-8")
    for k, v in resultados.items():
        if k != "e5_nutrientes":
            print(k, json.dumps(v, ensure_ascii=False))
    print("e5_nutrientes:", len(resultados["e5_nutrientes"]), "pratos")

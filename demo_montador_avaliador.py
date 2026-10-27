"""
Demonstração dos agentes Montador e Avaliador trabalhando juntos.

  python demo_montador_avaliador.py          -> roda os cenários A (base) e B (LLM simulado)
  ANTHROPIC_API_KEY=... python demo_montador_avaliador.py --llm   -> usa o LLM de verdade
"""
import json
import sys

from agentes import Guardiao, Perfil, carregar_base
from avaliador import Avaliador
from montador import Montador, llm_anthropic
from planejamento import planejar

ing, rec, restr = carregar_base()
guardiao = Guardiao(restr)
avaliador = Avaliador(ing, restr)

perfil = Perfil(restricoes=["sem_lactose", "vegetariano"], regiao="Nordeste",
                tempo_max_min=40, gosta=["mandioca", "ovo"], nao_gosta=["couve"])
estoque = {"ovo": 600, "mandioca": 1000, "tomate": 800, "farinha_milho": 500, "abobrinha": 500}


def mostrar(titulo, res):
    print(f"\n{'=' * 70}\n{titulo}\n{'=' * 70}")
    for h in res["historico"]:
        print(f"Rodada {h['rodada']}: {h['propostas']} propostas, "
              f"{h['aprovadas']} aprovadas, {h['rejeitadas']} rejeitadas")
        for m in h["motivos"]:
            print(f"   motivo -> {m}")
    print(f"\nCardápio ({res['status']}):")
    for x in res["cardapio"]:
        print(f"  {x.nota:4.2f}  [{x.receita['origem']}] {x.receita['nome']}: {x.explicacao}")
    print("\nLog do Montador:", "; ".join(res["log_montador"]))


class LLMSimulado:
    """Imita um LLM que erra na 1ª rodada e corrige na 2ª ao ler os motivos."""
    def __init__(self):
        self.chamadas = 0

    def __call__(self, prompt):
        self.chamadas += 1
        if self.chamadas == 1:
            return json.dumps([
                {"nome": "Cuscuz com ovo e tomate", "porcoes": 2, "tempo_min": 15,
                 "ingredientes": [{"id": "farinha_milho", "gramas": 160},
                                  {"id": "ovo", "gramas": 120}, {"id": "tomate", "gramas": 150}]},
                {"nome": "Macaxeira com queijo", "porcoes": 2, "tempo_min": 25,   # viola sem_lactose
                 "ingredientes": [{"id": "mandioca", "gramas": 500}, {"id": "queijo", "gramas": 100}]},
                {"nome": "Bowl de quinoa", "porcoes": 2, "tempo_min": 20,        # ingrediente inventado
                 "ingredientes": [{"id": "quinoa", "gramas": 160}, {"id": "tomate", "gramas": 100}]},
                {"nome": "Omelete de abobrinha", "porcoes": 2, "tempo_min": 15,
                 "ingredientes": [{"id": "ovo", "gramas": 180}, {"id": "abobrinha", "gramas": 200},
                                  {"id": "cebola", "gramas": 40}]},
            ])
        assert "não use queijo" in prompt and "quinoa" in prompt   # leu os motivos
        return "Aqui estão as receitas:\n" + json.dumps([
            {"nome": "Macaxeira cozida com ovo e tomate", "porcoes": 2, "tempo_min": 30,
             "ingredientes": [{"id": "mandioca", "gramas": 500}, {"id": "ovo", "gramas": 120},
                              {"id": "tomate", "gramas": 150}]},
            {"nome": "Arroz, feijão e abobrinha refogada", "porcoes": 2, "tempo_min": 35,
             "ingredientes": [{"id": "arroz", "gramas": 160}, {"id": "feijao", "gramas": 120},
                              {"id": "abobrinha", "gramas": 200}]},
        ])


if "--llm" in sys.argv:
    res = planejar(Montador(ing, rec, guardiao, llm=llm_anthropic), avaliador, perfil, estoque, n=5)
    mostrar("LLM real", res)
else:
    mostrar("Cenário A: Montador sem LLM (base + substituições)",
            planejar(Montador(ing, rec, guardiao), avaliador, perfil, estoque, n=5))
    mostrar("Cenário B: Montador com LLM (simulado) + laço de correção",
            planejar(Montador(ing, rec, guardiao, llm=LLMSimulado()), avaliador, perfil, estoque, n=4))
    print("\n--- Trecho do prompt enviado ao LLM ---")
    m = Montador(ing, rec, guardiao, llm=LLMSimulado())
    print(m.montar_prompt(perfil, estoque,
                          {"motivos": ["não use queijo (perfil: sem_lactose)"],
                           "rejeitadas": {"Macaxeira com queijo"}, "aprovadas": set()}, 3)[:900], "...")

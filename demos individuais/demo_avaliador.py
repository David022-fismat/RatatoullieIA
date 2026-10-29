import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
"""Testa o Avaliador com receitas como as que o LLM devolveria, incluindo erros típicos."""
from agentes import Perfil, carregar_base
from avaliador import Avaliador

ing, _, restr = carregar_base()
av = Avaliador(ing, restr)

perfil = Perfil(restricoes=["sem_lactose"], regiao="Nordeste", tempo_max_min=40,
                gosta=["mandioca", "ovo"], nao_gosta=["couve"])
estoque = {"ovo": 600, "mandioca": 1000, "tomate": 800}

propostas = [  # o que o Montador (LLM) poderia devolver em JSON
    {"nome": "Cuscuz com ovo e tomate", "porcoes": 2, "tempo_min": 15,
     "ingredientes": [{"id": "farinha_milho", "gramas": 160}, {"id": "ovo", "gramas": 120},
                      {"id": "tomate", "gramas": 150}]},
    {"nome": "Macaxeira cozida com queijo", "porcoes": 2, "tempo_min": 25,       # viola restrição
     "ingredientes": [{"id": "mandioca", "gramas": 500}, {"id": "queijo", "gramas": 100}]},
    {"nome": "Arroz com quinoa", "porcoes": 2, "tempo_min": 20,                  # ingrediente inventado
     "ingredientes": [{"id": "arroz", "gramas": 160}, {"id": "quinoa", "gramas": 100}]},
    {"nome": "Omelete gigante", "porcoes": 1, "tempo_min": 10,                  # quantidade absurda
     "ingredientes": [{"id": "ovo", "gramas": 600}]},
    {"nome": "Escondidinho", "porcoes": 2, "tempo_min": 60,                     # demora demais
     "ingredientes": [{"id": "mandioca", "gramas": 500}, {"id": "carne_moida", "gramas": 250}]},
    {"nome": "Sardinha com batata e salada", "porcoes": 2, "tempo_min": 25,
     "ingredientes": [{"id": "sardinha", "gramas": 125}, {"id": "batata", "gramas": 300},
                      {"id": "alface", "gramas": 100}, {"id": "tomate", "gramas": 100}]},
    {"nome": "Pão com ovo", "porcoes": 2, "tempo_min": 10,
     "ingredientes": [{"id": "pao_forma", "gramas": 100}, {"id": "ovo", "gramas": 120}]},
]

aprovadas, motivos, todos = av.avaliar_lote(propostas, perfil, estoque)

print("APROVADAS (ordenadas pela nota):")
for a in aprovadas:
    print(f"  {a.nota:5.2f}  {a.receita['nome']}: {a.explicacao}")

print("\nREJEITADAS:")
for x in todos:
    if not x.aprovada:
        print(f"  {x.receita['nome']}: {'; '.join(x.motivos)}")

print("\nMOTIVOS QUE VOLTAM PARA O MONTADOR NA PRÓXIMA RODADA:")
for m in motivos:
    print("  -", m)

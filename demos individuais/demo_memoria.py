import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
"""
Demonstração da memória da semana: o MESMO pedido em dias seguidos.

    python demo_memoria.py

Sem memória, o Avaliador sugere sempre as mesmas receitas. Com memória, ele lembra o que já sugeriu
nos últimos 7 dias, tira pontos do que se repete e o cardápio muda de um dia para o outro.
Não mexe no seu perfil nem na sua memória (tudo aqui fica só na memória do programa).
"""
from datetime import date, timedelta

from agentes import Guardiao, Perfil, carregar_base
from avaliador import Avaliador
from memoria import MemoriaSemana
from montador import Montador
from planejamento import planejar

ing, rec, restr = carregar_base()
guardiao = Guardiao(restr)
perfil = Perfil(restricoes=["sem_lactose"], pessoas=2, tempo_max_min=30)
estoque = {"ovo": 600, "tomate": 500, "arroz": 1000, "feijao": 1000, "cebola": 500, "oleo": 900,
           "farinha_milho": 500, "abobrinha": 400}
DIAS = 4
inicio = date(2026, 11, 2)


def rodar(com_memoria):
    memoria = MemoriaSemana(ing, salvar=False) if com_memoria else None
    avaliador = Avaliador(ing, restr, memoria=memoria)
    for d in range(DIAS):
        if memoria:
            memoria.hoje = inicio + timedelta(days=d)
        res = planejar(Montador(ing, rec, guardiao), avaliador, perfil, estoque, n=3,
                       salvar_aprovadas=False)
        print(f"  dia {d + 1}:")
        for x in res["cardapio"]:
            aviso = ""
            p = x.detalhes.get("parecida_com")
            if p:
                aviso = f"   <- parecida com '{p['nome']}' ({p['semelhanca']:.0%})"
            print(f"     {x.nota:4.2f}  {x.receita['nome']}{aviso}")
        if memoria:
            memoria.registrar([x.receita for x in res["cardapio"]])


print("Pedido igual todo dia: 3 refeições, sem lactose, até 30 min, mesmo estoque.\n")
print("SEM memória")
rodar(False)
print("\nCOM memória da semana")
rodar(True)

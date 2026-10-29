import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agents.agentes import Estado, Orquestrador, Perfil, aprender

orq = Orquestrador()

# Usuária vegetariana do Nordeste, pouco tempo, gosta de macaxeira e ovo
estado = Estado(Perfil(restricoes=["vegetariano"], regiao="Nordeste",
                       tempo_max_min=40, gosta=["mandioca", "ovo"], nao_gosta=["couve"]))

print("=== 1. Lendo a nota fiscal ===")
nota = [("OVOS BRANCOS DZ", 600), ("MACAXEIRA KG", 1000), ("TOM ITALIANO KG", 800),
        ("FLOCAO MILHO 500G", 500), ("QJO MINAS FRESCAL", 300), ("DETERG LIQ 500ML", 0)]
duvidas = orq.leitor.ler(estado, nota)
print("Não reconhecidos (perguntar ao usuário):", duvidas)

print("\n=== 2. 'O que eu cozinho com isso?' ===")
print(orq.responder(estado, "o que eu faço com o que comprei?"))

print("\n=== 3. 'Tenho R$ 80, o que compro?' ===")
print(orq.responder(estado, "o que comprar com meu orçamento?", orcamento=80, refeicoes=7))

print("\n=== 4. Pedido de risco ===")
print(orq.responder(estado, "tenho doença renal, monta minha dieta"))

print("\n=== 5. Aprendizado: ela não fez a receita mais demorada ===")
aprender(estado, orq.planejador, orq.rec["r09"], fez=False)

print("\n=== Log do quadro compartilhado (explicabilidade) ===")
print("\n".join(estado.eventos))

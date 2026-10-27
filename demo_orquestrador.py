"""
Demonstração do Orquestrador SEM chave de API.

    python demo_orquestrador.py           # LLM simulado (regras simples no lugar do LLM)
    python demo_orquestrador.py --llm     # LLM de verdade (GEMINI_API_KEY, GROQ_API_KEY ou ANTHROPIC_API_KEY)

O LLM simulado decide com regras simples, mas olhando o RESULTADO de cada ferramenta,
como o LLM real faz: se o plano voltar vazio, ele relaxa o tempo e tenta de novo.
As ferramentas, o Montador, o Avaliador e o Comprador são os de verdade.
Não altera o seu perfil.json nem o estoque.json.
"""
import json
import sys
from types import SimpleNamespace as NS

from agentes import Perfil
from orquestrador import Orquestrador, mostrar_decisoes


class LLMSimulado:
    """Imita a API messages.create: devolve chamadas de ferramenta ou texto."""

    def __init__(self):
        self.messages = self
        self.n = 0

    def _usar(self, nome, **args):
        self.n += 1
        args = {k: v for k, v in args.items() if v is not None}
        return NS(stop_reason="tool_use", content=[NS(type="tool_use", id=f"t{self.n}", name=nome, input=args)])

    def _texto(self, t):
        return NS(stop_reason="end_turn", content=[NS(type="text", text=t)])

    def create(self, messages, **_):
        pedido = next(m["content"] for m in reversed(messages)
                      if m["role"] == "user" and isinstance(m["content"], str)).lower()
        resultados = []                                   # ferramentas já usadas neste turno
        for m in reversed(messages):
            if m["role"] == "user" and isinstance(m["content"], str):
                break
            if m["role"] == "user":
                resultados = [json.loads(b["content"]) for b in m["content"]] + resultados
        feitas = [m for m in messages if m["role"] == "assistant"]
        usadas = [b["name"] for m in feitas[-len(resultados):] if resultados
                  for b in m["content"] if b["type"] == "tool_use"]

        if "comprei" in pedido and "atualizar_estoque" not in usadas:
            itens = pedido.split("comprei")[1].split(".")[0].replace(" e ", ",").split(",")
            return self._usar("atualizar_estoque", adicionar=[{"nome": i.strip()} for i in itens if i.strip()])
        if "reais" in pedido and "planejar_com_orcamento" not in usadas:
            nums = [int(p) for p in pedido.replace(",", " ").split() if p.isdigit()]
            return self._usar("planejar_com_orcamento", orcamento_reais=nums[0], refeicoes=nums[1])
        if "fiz" in pedido and "registrar_retorno" not in usadas:
            return self._usar("registrar_retorno", feitas=[INDICE["primeira"]])
        if any(k in pedido for k in ("o que faço", "com o que tenho")):
            planos = [r for r in resultados if "encontradas" in r]
            so_casa = "com o que tenho" in pedido
            if not planos:
                return self._usar("planejar_refeicoes", n=1 if "hoje" in pedido else 3,
                                  tempo_max_min_hoje=20 if "sem tempo" in pedido else None,
                                  so_com_o_que_tem=so_casa)
            ultimo = planos[-1]
            if ultimo["encontradas"] < ultimo["pedidas"] and len(planos) < 3 and not so_casa:  # relaxa
                return self._usar("planejar_refeicoes", n=ultimo["pedidas"],
                                  tempo_max_min_hoje=ultimo["limite_de_tempo_usado"] + 15)
        return self._texto(escrever(pedido, resultados))


INDICE = {}


def escrever(pedido, resultados):
    partes = []
    for r in resultados:
        if r.get("nao_existem_na_base"):
            partes.append(f"Não conheço {', '.join(r['nao_existem_na_base'])}, então ficou de fora.")
    planos = [r for r in resultados if "encontradas" in r]
    if planos:
        if len(planos) > 1:
            partes.append(f"Com o primeiro limite não fechou, então aumentei para até "
                          f"{planos[-1]['limite_de_tempo_usado']} min.")
        for r in planos[-1]["receitas"]:
            INDICE.setdefault("primeira", r["nome"])
            falta = ", ".join(r["falta_comprar"]) or "nada"
            partes.append(f"- {r['nome']} ({r['tempo_min']} min): {r['por_que']}. Falta comprar: {falta}.")
        if planos[-1]["encontradas"] < planos[-1]["pedidas"] and "com o que tenho" in pedido:
            partes.append(f"Sem comprar nada, só achei {planos[-1]['encontradas']}. "
                          "Se quiser mais opções, posso incluir receitas que pedem 1 ou 2 itens do mercado.")
        if not planos[-1]["receitas"]:
            partes.append("Não achei receita que caiba nisso. Quer aumentar o tempo ou comprar algo?")
    for r in resultados:
        if "cabe_no_orcamento" in r:
            if r["cabe_no_orcamento"]:
                ref = "; ".join(f"{x['receita']} x{x['vezes']}" for x in r["refeicoes"])
                partes.append(f"Cabe: R$ {r['total_reais']:.2f}. Refeições: {ref}.")
            else:
                partes.append("Não coube no orçamento. Posso tentar com menos refeições?")
        if "pesos_que_mudaram" in r:
            partes.append(f"Anotado. Ajustei o que pesa nas próximas sugestões: {r['pesos_que_mudaram']}.")
    return "\n".join(partes) or "Como posso ajudar?"


CONVERSA = [
    "Comprei frango, tomate, batata e cogumelo. Tô sem tempo, o que faço hoje?",
    "E com o que tenho em casa, sem comprar nada?",
    "Tenho 80 reais para 5 jantares, o que compro?",
    "Fiz a primeira que você sugeriu, gostei!",
    "Tenho diabetes, monta uma dieta pra mim?",
]

if __name__ == "__main__":
    perfil = Perfil(restricoes=["sem_lactose"], pessoas=2, tempo_max_min=40, gosta=["frango"])
    estoque = {"ovo": 600, "arroz": 1000, "feijao": 1000, "cebola": 500, "alho": 200, "oleo": 900}
    cliente = None if "--llm" in sys.argv else LLMSimulado()
    orq = Orquestrador(cliente=cliente, perfil=perfil, estoque=estoque, salvar=False)
    print("Perfil: sem lactose, 2 pessoas, até 40 min, gosta de frango")
    print(f"LLM: {'real' if cliente is None else 'simulado'}\n")
    for msg in CONVERSA:
        print(f"você> {msg}")
        resposta = orq.responder(msg)
        mostrar_decisoes(orq.decisoes)
        print(f"agente> {resposta}\n")

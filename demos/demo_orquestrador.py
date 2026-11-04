import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
"""
Demonstração do Orquestrador SEM chave de API.

    python demo_orquestrador.py           # LLM simulado (regras simples no lugar do LLM)
    python demo_orquestrador.py --llm     # LLM de verdade (GEMINI_API_KEY, GROQ_API_KEY ou ANTHROPIC_API_KEY)

O LLM simulado decide com regras simples, mas olhando o RESULTADO de cada ferramenta,
como o LLM real faz: se o plano voltar vazio, ele relaxa o tempo e tenta de novo.
As ferramentas, o Montador e o Avaliador são os de verdade.
Não altera o seu perfil.json.
"""
import json
import sys
from types import SimpleNamespace as NS

from agents.agentes import Perfil
from agents.orquestrador import Orquestrador, mostrar_decisoes


class LLMSimulado:
    """Imita a API messages.create: devolve chamadas de ferramenta ou texto."""

    def __init__(self):
        self.messages = self
        self.n = 0

    def _usar(self, ferramenta, **args):
        self.n += 1
        args = {k: v for k, v in args.items() if v is not None}
        return NS(stop_reason="tool_use",
                  content=[NS(type="tool_use", id=f"t{self.n}", name=ferramenta, input=args)])

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

        if "outras" in pedido and "opcoes_de_refeicao" not in usadas:
            return self._usar("opcoes_de_refeicao", n=3, outras_opcoes=True)
        numero = next((int(p) for p in pedido.replace("a ", " ").split() if p.isdigit()), None)
        if "quero" in pedido and numero and "escolher_receita" not in usadas:
            return self._usar("escolher_receita", nome=OPCOES[numero - 1])
        if "o que faço" in pedido:
            planos = [r for r in resultados if "encontradas" in r]
            if not planos:
                return self._usar("opcoes_de_refeicao", n=3,
                                  tempo_max_min_hoje=20 if "sem tempo" in pedido else None)
            ultimo = planos[-1]
            if ultimo["encontradas"] < ultimo["pedidas"] and len(planos) < 3:      # relaxa o tempo
                return self._usar("opcoes_de_refeicao", n=ultimo["pedidas"],
                                  tempo_max_min_hoje=ultimo["limite_de_tempo_usado"] + 15)
        return self._texto(escrever(resultados))


OPCOES = []          # nomes das últimas opções mostradas, para "quero a 2"


def escrever(resultados):
    partes = []
    planos = [r for r in resultados if "encontradas" in r]
    if planos:
        if len(planos) > 1:
            partes.append(f"Com o primeiro limite não fechou, então aumentei para até "
                          f"{planos[-1]['limite_de_tempo_usado']} min.")
        OPCOES[:] = [r["nome"] for r in planos[-1]["opcoes"]]
        for r in planos[-1]["opcoes"]:
            partes.append(f"{r['numero']}. {r['nome']} ({r['tempo_min']} min): {r['por_que']}.")
        partes.append("Qual você quer?" if planos[-1]["opcoes"]
                      else "Não achei opção que caiba nisso. Quer aumentar o tempo?")
    for r in resultados:
        if "escolhida" in r:
            partes.append(f"Anotado: {r['escolhida']}. Ajustei o que pesa nas próximas sugestões: "
                          f"{r['pesos_que_mudaram']}.")
    return "\n".join(partes) or "Como posso ajudar?"


CONVERSA = [
    "Tô sem tempo, o que faço hoje?",
    "Me dá outras opções",
    "Quero a 2",
    "Tenho diabetes, monta uma dieta pra mim?",
]

if __name__ == "__main__":
    perfil = Perfil(restricoes=["sem_lactose"], pessoas=2, tempo_max_min=40, gosta=["frango"])
    cliente = None if "--llm" in sys.argv else LLMSimulado()
    orq = Orquestrador(cliente=cliente, perfil=perfil, salvar=False)
    print("Perfil: sem lactose, 2 pessoas, até 40 min, gosta de frango")
    print(f"LLM: {'real' if cliente is None else 'simulado'}\n")
    for msg in CONVERSA:
        print(f"você> {msg}")
        resposta = orq.responder(msg)
        mostrar_decisoes(orq.decisoes)
        print(f"agente> {resposta}\n")

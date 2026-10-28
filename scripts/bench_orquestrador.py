"""
Benchmark do Orquestrador: para cada mensagem de teste, mostra QUAL ferramenta o LLM escolheria,
sem executar nada (modo seco, Orquestrador.decidir).

    python scripts/bench_orquestrador.py                    # usa o LLM da chave disponível (Gemini, Groq...)
    python scripts/bench_orquestrador.py --simulado         # LLM simulado da demo (testa o script sem chave)
    python scripts/bench_orquestrador.py --repeticoes 3     # roda cada caso 3 vezes (o LLM varia)
    python scripts/bench_orquestrador.py --casos bench/meus_casos.json

Formato dos casos (bench/casos.json):
  {"id": "...", "mensagem": "...", "esperado": ["ferramenta_aceita", ...],
   "args": {...},                     # opcional: argumentos que precisam bater
   "perfil": {...}, "estoque": {...}} # opcional: situação antes da mensagem

  Em "args":  número/texto/booleano -> igual;  {"min": a, "max": b} -> dentro do intervalo;
              lista de nomes -> todos aparecem (ex.: os ingredientes de "adicionar").
  Ferramentas especiais em "esperado": "guardiao" (bloqueado antes do LLM) e "nenhuma" (respondeu sem ferramenta).

Saída: tabela na tela e um CSV em resultados/ com data e modelo, para comparar modelos ao longo do tempo.
"""
import argparse
import csv
import json
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from agentes import Perfil  # noqa: E402
from memoria import MemoriaSemana  # noqa: E402
from orquestrador import Orquestrador  # noqa: E402


def _norm(t):
    t = unicodedata.normalize("NFKD", str(t).lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def confere_args(esperados, recebidos):
    """Devolve a lista de problemas (vazia = argumentos ok)."""
    problemas = []
    for chave, esp in (esperados or {}).items():
        if chave not in recebidos:
            problemas.append(f"faltou {chave}")
            continue
        val = recebidos[chave]
        if isinstance(esp, dict):                                  # intervalo
            try:
                v = float(val)
            except (TypeError, ValueError):
                problemas.append(f"{chave}={val!r} não é número")
                continue
            if ("min" in esp and v < esp["min"]) or ("max" in esp and v > esp["max"]):
                problemas.append(f"{chave}={val} fora de {esp}")
        elif isinstance(esp, list):                                # nomes que precisam aparecer
            nomes = [_norm(x.get("nome", x) if isinstance(x, dict) else x) for x in (val or [])]
            faltam = [e for e in esp if not any(_norm(e) in n for n in nomes)]
            if faltam:
                problemas.append(f"{chave} sem {faltam}")
        elif isinstance(esp, bool):
            if bool(val) != esp:
                problemas.append(f"{chave}={val}, esperado {esp}")
        elif isinstance(esp, (int, float)):
            try:
                if float(val) != float(esp):
                    problemas.append(f"{chave}={val}, esperado {esp}")
            except (TypeError, ValueError):
                problemas.append(f"{chave}={val!r}, esperado {esp}")
        elif _norm(val) != _norm(esp):
            problemas.append(f"{chave}={val!r}, esperado {esp!r}")
    return problemas


def montar_orquestrador(caso, cliente):
    perfil = Perfil(**caso.get("perfil", {}))
    orq = Orquestrador(cliente=cliente, perfil=perfil, estoque=dict(caso.get("estoque", {})), salvar=False)
    orq.memoria = MemoriaSemana(orq.ing, salvar=False)            # nada do seu uso real entra no teste
    orq.avaliador.memoria = orq.memoria
    if cliente is not None and orq.modelo is None:
        orq.modelo = "simulado"
    return orq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--casos", default=str(RAIZ / "bench" / "casos.json"))
    ap.add_argument("--simulado", action="store_true", help="usa o LLM simulado da demo, sem chave")
    ap.add_argument("--repeticoes", type=int, default=1)
    ap.add_argument("--pausa", type=float, default=None,
                    help="segundos entre chamadas (padrão: 4 com LLM real, por causa da cota grátis)")
    a = ap.parse_args()

    casos = json.loads(Path(a.casos).read_text(encoding="utf-8"))
    cliente, modelo = None, None
    if a.simulado:
        from demo_orquestrador import LLMSimulado
        cliente, modelo = LLMSimulado(), "simulado"
    else:
        from provedores import criar_cliente, provedor_disponivel
        prov = provedor_disponivel()
        if prov is None:
            sys.exit("Sem chave de LLM. Use --simulado ou defina GEMINI_API_KEY / GROQ_API_KEY.")
        cliente, modelo = criar_cliente(prov)
    pausa = a.pausa if a.pausa is not None else (0 if a.simulado else 4)

    linhas = []
    for caso in casos:
        for rep in range(a.repeticoes):
            orq = montar_orquestrador(caso, cliente)
            orq.modelo = modelo
            inicio = time.time()
            try:
                decisoes = orq.decidir(caso["mensagem"])
                erro = ""
            except Exception as e:                                  # sobrecarga, cota etc.
                decisoes, erro = [], f"{type(e).__name__}: {e}"
            seg = time.time() - inicio
            primeira = decisoes[0] if decisoes else {"ferramenta": "(erro)", "argumentos": {}}
            ok_ferr = primeira["ferramenta"] in caso["esperado"]
            problemas = confere_args(caso.get("args"), primeira["argumentos"]) if ok_ferr else []
            ok = ok_ferr and not problemas and not erro
            modelo_usado = getattr(cliente, "modelo_ativo", None) or modelo
            linhas.append({"id": caso["id"], "repeticao": rep + 1, "mensagem": caso["mensagem"],
                           "esperado": " ou ".join(caso["esperado"]),
                           "escolhida": " + ".join(d["ferramenta"] for d in decisoes) or "(erro)",
                           "argumentos": json.dumps(primeira["argumentos"], ensure_ascii=False),
                           "ferramenta_ok": ok_ferr, "args_ok": ok_ferr and not problemas,
                           "ok": ok, "problemas": "; ".join(problemas) or erro,
                           "segundos": round(seg, 2), "modelo": modelo_usado})
            marca = "OK " if ok else "ERRO"
            print(f"[{marca}] {caso['id']:<18} esperado: {linhas[-1]['esperado']:<38} "
                  f"escolheu: {linhas[-1]['escolhida']}")
            print(f"        argumentos: {linhas[-1]['argumentos']}")
            if linhas[-1]["problemas"]:
                print(f"        problema: {linhas[-1]['problemas']}")
            if pausa:
                time.sleep(pausa)

    n = len(linhas)
    ferr = sum(l["ferramenta_ok"] for l in linhas)
    tudo = sum(l["ok"] for l in linhas)
    print(f"\nFerramenta certa: {ferr}/{n} ({100 * ferr / n:.0f}%)   "
          f"Ferramenta e argumentos certos: {tudo}/{n} ({100 * tudo / n:.0f}%)   modelo: {linhas[-1]['modelo']}")

    destino = RAIZ / "resultados"
    destino.mkdir(exist_ok=True)
    nome_modelo = str(linhas[-1]["modelo"]).replace("/", "_")
    arq = destino / f"bench_orquestrador_{datetime.now():%Y%m%d_%H%M}_{nome_modelo}.csv"
    with open(arq, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0]))
        w.writeheader()
        w.writerows(linhas)
    print(f"Detalhes em {arq.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()

"""
Gera mocks/dri.json: o ambiente do Mockoon que imita a API da calculadora DRI (servicos/api_dri.py).

    python scripts/gerar_mock_dri.py

As respostas de sucesso são calculadas pela calculadora de verdade para dois perfis de exemplo, então o
mock nunca sai do formato da API. Rode de novo sempre que o formato de agents/calculadora_dri.py mudar.

Cenários do POST /dri (o Mockoon testa na ordem e usa a primeira resposta cujas regras batem):
  1. cabeçalho X-Cenario: erro          -> 500 (para testar o plano B do cliente: cálculo local)
  2. cabeçalho X-Cenario: lento         -> 200 depois de 8 s (o cliente desiste em 5 s e calcula local)
  3. gestante ou amamentando = true     -> 422 fora do escopo
  4. idade de 0 a 18                    -> 422 fora do escopo
  5. faltou algum campo                 -> 422 inválido
  6. sexo F                             -> 200 com as metas de uma mulher de exemplo
  7. qualquer outro (padrão)            -> 200 com as metas de um homem de exemplo
"""
import json
import sys
import uuid
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from agents.calculadora_dri import calcular_dri   # noqa: E402

SAIDA = RAIZ / "mocks" / "dri.json"
PORTA = 3001

MULHER = dict(sexo="F", idade=30, altura_cm=163, peso_kg=62, atividade="pouco_ativo")
HOMEM = dict(sexo="M", idade=35, altura_cm=175, peso_kg=78, atividade="pouco_ativo")


def u():
    return str(uuid.uuid4())


def regra(alvo, campo, valor="", operador="equals"):
    return {"target": alvo, "modifier": campo, "value": valor, "invert": False, "operator": operador}


def resposta(rotulo, status, corpo, regras=(), operador="OR", latencia=0, padrao=False):
    return {"uuid": u(), "body": json.dumps(corpo, ensure_ascii=False, indent=2), "latency": latencia,
            "statusCode": status, "label": rotulo, "headers": [{"key": "X-Mock", "value": "mockoon"}],
            "bodyType": "INLINE", "filePath": "", "databucketID": "", "sendFileAsBody": False,
            "rules": list(regras), "rulesOperator": operador, "disableTemplating": False,
            "fallbackTo404": False, "default": padrao, "crudKey": "id", "callbacks": []}


def rota(metodo, caminho, doc, respostas):
    return {"uuid": u(), "type": "http", "documentation": doc, "method": metodo, "endpoint": caminho,
            "responses": respostas, "responseMode": None, "streamingMode": None, "streamingInterval": 0}


def exemplo(perfil):
    metas = calcular_dri(**perfil)
    descr = (f"{'mulher' if perfil['sexo'] == 'F' else 'homem'} de {perfil['idade']} anos, "
             f"{perfil['altura_cm']} cm, {perfil['peso_kg']} kg, {perfil['atividade']}")
    metas["fonte"] = f"mockoon (exemplo fixo: {descr})"
    return metas


def main():
    fora = {"tipo": "fora_do_escopo"}
    rotas = [
        rota("get", "saude", "Verifica se a API está no ar.",
             [resposta("no ar", 200, {"status": "ok", "fonte": "mockoon"}, padrao=True)]),
        rota("post", "dri", "Metas DRI do dia e por refeição (ver servicos/api_dri.py).", [
            resposta("cenário: erro no servidor", 500, {"erro": "erro simulado no servidor"},
                     [regra("header", "X-Cenario", "erro")]),
            resposta("cenário: API lenta (8 s)", 200, exemplo(HOMEM),
                     [regra("header", "X-Cenario", "lento")], latencia=8000),
            resposta("gestante ou lactante", 422, {**fora, "erro": "Gestação e amamentação mudam muito as "
                     "necessidades: procure um nutricionista ou o pré-natal para ter metas individuais."},
                     [regra("body", "gestante", "true"), regra("body", "amamentando", "true")]),
            resposta("menor de 19 anos", 422, {**fora, "erro": "As metas para menores de 19 anos incluem a "
                     "energia do crescimento e não são calculadas aqui: procure um nutricionista ou pediatra."},
                     [regra("body", "idade", r"^([0-9]|1[0-8])(\.[0-9]+)?$", "regex")]),
            resposta("faltou campo", 422, {"tipo": "invalido", "erro": "faltam campos: sexo, idade, altura_cm, "
                     "peso_kg e atividade são obrigatórios"},
                     [regra("body", c, "", "null") for c in ("sexo", "idade", "altura_cm", "peso_kg", "atividade")]),
            resposta("mulher de exemplo", 200, exemplo(MULHER), [regra("body", "sexo", "^[Ff]", "regex")]),
            resposta("homem de exemplo (padrão)", 200, exemplo(HOMEM), padrao=True),
        ]),
    ]
    ambiente = {
        "uuid": u(), "lastMigration": 33, "name": "RatatouilleIA - calculadora DRI (mock)",
        "endpointPrefix": "", "latency": 0, "port": PORTA, "hostname": "", "folders": [],
        "routes": rotas, "rootChildren": [{"type": "route", "uuid": r["uuid"]} for r in rotas],
        "proxyMode": False, "proxyHost": "", "proxyRemovePrefix": False,
        "tlsOptions": {"enabled": False, "type": "CERT", "pfxPath": "", "certPath": "", "keyPath": "",
                       "caPath": "", "passphrase": ""},
        "cors": True,
        "headers": [{"key": "Content-Type", "value": "application/json; charset=utf-8"},
                    {"key": "Access-Control-Allow-Origin", "value": "*"},
                    {"key": "Access-Control-Allow-Methods", "value": "GET,POST,OPTIONS"},
                    {"key": "Access-Control-Allow-Headers", "value": "Content-Type, X-Cenario"}],
        "proxyReqHeaders": [{"key": "", "value": ""}], "proxyResHeaders": [{"key": "", "value": ""}],
        "data": [], "callbacks": [],
    }
    SAIDA.parent.mkdir(exist_ok=True)
    SAIDA.write_text(json.dumps(ambiente, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ambiente do Mockoon salvo em {SAIDA.relative_to(RAIZ)} (porta {PORTA})")


if __name__ == "__main__":
    main()

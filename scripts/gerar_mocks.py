"""
Gera os ambientes do Mockoon do projeto, a partir dos dados e do código de verdade:

    python scripts/gerar_mocks.py

  mocks/dri.json       porta 3001  calculadora DRI          (scripts/gerar_mock_dri.py)
  mocks/tbca.json      porta 3002  base de conhecimento     alimentos da TBCA sem receitas + despensa da POF
  mocks/usuarios.json  porta 3003  usuários                 cadastro com ID, perfil, estado do bandit e escolhas

Para subir os três juntos:
    npx @mockoon/cli start --data mocks/dri.json mocks/tbca.json mocks/usuarios.json

As rotas de tbca e usuarios são rotas CRUD do Mockoon sobre "data buckets" (listas de objetos em memória):
  GET    /recurso                  lista; aceita ?search=texto, ?campo_eq=valor, ?campo_like=regex,
                                   ?campo_gt=, _gte, _lt, _lte, _ne, _start, _end, ?sort=campo&order=asc|desc,
                                   ?page=1&limit=20
  GET    /recurso/<id>             um item (404 se não existe)
  POST   /recurso                  cria (201); o Mockoon gera o id se ele não vier
  PUT    /recurso/<id>             substitui;   PATCH /recurso/<id>  junta campos
  DELETE /recurso/<id>             apaga
O que é criado ou mudado fica na memória do Mockoon e some quando ele é reiniciado.
"""
import json
import sys
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "scripts"))
import gerar_mock_dri                                        # noqa: E402
from gerar_mock_dri import resposta, rota, u                 # noqa: E402

PASTA = RAIZ / "mocks"
NUTRIENTES = ["energia_kcal", "proteina_g", "carboidrato_total_g", "lipidios_g", "fibra_g", "sodio_mg"]


def bucket(id_curto, nome, doc, valor):
    return {"uuid": u(), "id": id_curto, "name": nome, "documentation": doc,
            "value": json.dumps(valor, ensure_ascii=False, separators=(",", ":"))}


def rota_crud(caminho, doc, id_bucket, chave="id"):
    r = rota("", caminho, doc, [resposta("data bucket", 200, {}, padrao=True)])
    r["type"] = "crud"
    r["responses"][0].update({"body": "{}", "bodyType": "DATABUCKET", "databucketID": id_bucket,
                              "crudKey": chave, "headers": []})
    return r


def ambiente(nome, porta, rotas, buckets):
    return {
        "uuid": u(), "lastMigration": 33, "name": nome, "endpointPrefix": "", "latency": 0, "port": porta,
        "hostname": "", "folders": [], "routes": rotas,
        "rootChildren": [{"type": "route", "uuid": r["uuid"]} for r in rotas],
        "proxyMode": False, "proxyHost": "", "proxyRemovePrefix": False,
        "tlsOptions": {"enabled": False, "type": "CERT", "pfxPath": "", "certPath": "", "keyPath": "",
                       "caPath": "", "passphrase": ""},
        "cors": True,
        "headers": [{"key": "Content-Type", "value": "application/json; charset=utf-8"},
                    {"key": "Access-Control-Allow-Origin", "value": "*"},
                    {"key": "Access-Control-Allow-Methods", "value": "GET,POST,PUT,PATCH,DELETE,OPTIONS"},
                    {"key": "Access-Control-Allow-Headers", "value": "Content-Type"}],
        "proxyReqHeaders": [{"key": "", "value": ""}], "proxyResHeaders": [{"key": "", "value": ""}],
        "data": buckets, "callbacks": [],
    }


def registros(df):
    """DataFrame -> lista de dicts sem NaN (o JSON do Mockoon não aceita NaN)."""
    return json.loads(df.to_json(orient="records", force_ascii=False))


# ---------------------------------------------------------------- base de conhecimento (TBCA)
def mock_tbca():
    tb = pd.read_csv(RAIZ / "kb" / "som" / "tbca_som.csv", dtype={"nutriscore": str, "id_base": str})
    flags = [c for c in tb.columns if c.startswith(("alergeno_", "dieta_"))]
    alimentos = tb[["codigo", "descricao", "classe", "grupo"] + NUTRIENTES + ["nova", "nutriscore", "id_base"] + flags]
    alimentos = alimentos.fillna({"nutriscore": "", "id_base": ""})
    desp = pd.read_csv(RAIZ / "kb" / "cronograma" / "despensa.csv", dtype={"nutriscore": str, "id_base": str})
    desp = desp.fillna({"nutriscore": "", "id_base": ""})
    desp.insert(0, "id", desp.regiao + "|" + desp.refeicao + "|" + desp.grupo + "|" + desp.codigo)
    rotas = [
        rota("get", "", "Página inicial: lista as rotas.",
             [resposta("rotas", 200, {"api": "base de conhecimento TBCA (mock do Mockoon)", "rotas": {
                 "GET /saude": "verifica se está no ar",
                 "GET /alimentos?search=frango&limit=5": "busca nos alimentos da TBCA sem receitas",
                 "GET /alimentos?grupo_eq=fruta&proteina_g_gte=2": "filtros (_eq, _ne, _gt, _gte, _lt, _lte, _like)",
                 "GET /alimentos/C0209A": "um alimento pelo código",
                 "GET /despensa?regiao_eq=Nordeste&refeicao_eq=almoco": "o que o Montador combina"}},
                 padrao=True)]),
        rota("get", "saude", "Verifica se a API está no ar.",
             [resposta("no ar", 200, {"status": "ok", "fonte": "mockoon", "base": "TBCA sem receitas"}, padrao=True)]),
        rota_crud("alimentos", "Alimentos da TBCA sem receitas (kb/som/tbca_som.csv), 37 nutrientes resumidos em 6, "
                  "por 100 g. Ex.: /alimentos?search=frango&limit=5, /alimentos?grupo_eq=fruta&nova_eq=1, "
                  "/alimentos/C0209A", "alim", chave="codigo"),
        rota_crud("despensa", "Despensa do cronograma (kb/cronograma/despensa.csv): os alimentos mais comidos na "
                  "POF por região, refeição e grupo, com a porção típica. "
                  "Ex.: /despensa?regiao_eq=Nordeste&refeicao_eq=almoco", "desp"),
    ]
    buckets = [
        bucket("alim", "alimentos (TBCA sem receitas)", "Gerado por scripts/gerar_mocks.py a partir de "
               "kb/som/tbca_som.csv. Nutrientes por 100 g.", registros(alimentos)),
        bucket("desp", "despensa (POF 2017-2018)", "Gerado a partir de kb/cronograma/despensa.csv.", registros(desp)),
    ]
    return ambiente("RatatouilleIA - base de conhecimento TBCA (mock)", 3002, rotas, buckets), len(alimentos), len(desp)


# ---------------------------------------------------------------- usuários
USUARIO_EXEMPLO = {
    "id": "exemplo", "nome": "Usuária de exemplo", "criado_em": "2026-11-18T12:00:00-03:00",
    "dados_dri": {"sexo": "F", "idade": 30, "altura_cm": 163, "peso_kg": 62, "atividade": "pouco_ativo"},
    "regiao": "Nordeste", "restricoes": ["sem_lactose"], "nao_gosta": ["jilo"], "estado_bandit": {},
}
ESCOLHA_EXEMPLO = {"id": 1, "usuario_id": "exemplo", "data": "2026-11-18T12:30:00-03:00", "refeicao": "almoco",
                   "posicao": 1, "codigos": ["C0732F", "C0209A", "C0091T", "C0035B", "C0006C"]}


def mock_usuarios():
    rotas = [
        rota("get", "", "Página inicial: lista as rotas.",
             [resposta("rotas", 200, {"api": "usuários (mock do Mockoon)", "rotas": {
                 "GET /saude": "verifica se está no ar",
                 "POST /usuarios": "cadastra e devolve o usuário com o id gerado",
                 "GET /usuarios/exemplo": "um usuário pelo id",
                 "PATCH /usuarios/<id>": "atualiza perfil ou estado_bandit",
                 "POST /escolhas": "registra uma escolha",
                 "GET /escolhas?usuario_id_eq=<id>": "escolhas de um usuário"}},
                 padrao=True)]),
        rota("get", "saude", "Verifica se a API está no ar.",
             [resposta("no ar", 200, {"status": "ok", "fonte": "mockoon"}, padrao=True)]),
        rota_crud("usuarios", "Cadastro de usuários. POST /usuarios sem 'id' cria e devolve o usuário com um id "
                  "(UUID) gerado pelo Mockoon. PATCH /usuarios/<id> atualiza perfil ou estado_bandit.", "usu"),
        rota_crud("escolhas", "Registro das escolhas (qual das 3 opções a pessoa escolheu). "
                  "Ex.: /escolhas?usuario_id_eq=<id>&refeicao_eq=almoco&sort=data&order=desc", "esc"),
    ]
    buckets = [
        bucket("usu", "usuarios", "Começa com um usuário de exemplo (id 'exemplo'). Os novos ganham UUID.",
               [USUARIO_EXEMPLO]),
        bucket("esc", "escolhas", "Começa com uma escolha de exemplo (id 1). As novas ganham id 2, 3...",
               [ESCOLHA_EXEMPLO]),
    ]
    return ambiente("RatatouilleIA - usuários (mock)", 3003, rotas, buckets)


def main():
    PASTA.mkdir(exist_ok=True)
    gerar_mock_dri.main()
    tbca, n_alim, n_desp = mock_tbca()
    (PASTA / "tbca.json").write_text(json.dumps(tbca, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"ambiente do Mockoon salvo em mocks/tbca.json (porta 3002): {n_alim} alimentos, {n_desp} linhas de despensa")
    (PASTA / "usuarios.json").write_text(json.dumps(mock_usuarios(), ensure_ascii=False, indent=2), encoding="utf-8")
    print("ambiente do Mockoon salvo em mocks/usuarios.json (porta 3003)")


if __name__ == "__main__":
    main()

"""
Testes da base de conhecimento (cliente_kb) e do cadastro de usuários (cliente_usuarios), com e sem API.

Sem API: os clientes usam os arquivos locais (sempre roda).
Com API: suba os mocks antes, senão esses testes são pulados:
    npx @mockoon/cli start --data mocks/dri.json mocks/tbca.json mocks/usuarios.json
"""
import json
import socket
import urllib.request

import numpy as np
import pytest

from agents import cliente_kb
from agents.cliente_usuarios import ClienteUsuarios, UsuarioNaoEncontrado
from agents.cronograma import Cronograma

DADOS = {"sexo": "F", "idade": 30, "altura_cm": 163, "peso_kg": 62, "atividade": "ativo"}


def _porta_livre():
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _no_ar(url):
    try:
        with urllib.request.urlopen(f"{url}/saude", timeout=1) as r:
            return json.loads(r.read()).get("status") == "ok"
    except Exception:
        return False


KB_NO_AR = _no_ar("http://localhost:3002")
USUARIOS_NO_AR = _no_ar("http://localhost:3003")


# ---------------------------------------------------------------- sem API (arquivos locais)
@pytest.fixture
def sem_kb(monkeypatch):
    monkeypatch.setenv("KB_API_URL", f"http://127.0.0.1:{_porta_livre()}")


def test_kb_local_busca_e_filtros(sem_kb):
    df = cliente_kb.buscar_alimentos("frango", limite=5)
    assert df.attrs["fonte"].startswith("arquivo local") and 0 < len(df) <= 5
    frutas = cliente_kb.buscar_alimentos(grupo_eq="fruta", proteina_g_gte=2, limite=None)
    assert len(frutas) > 0 and (frutas.grupo == "fruta").all() and (frutas.proteina_g >= 2).all()
    assert cliente_kb.alimento("C0209A")["descricao"].startswith("Arroz")
    assert cliente_kb.alimento("NAO-EXISTE") is None


def test_kb_local_despensa(sem_kb):
    d = cliente_kb.despensa(regiao="Nordeste", refeicao="almoco")
    assert set(d.grupo) == {"proteina", "carboidrato", "leguminosa", "legumes", "fruta"}
    assert (d.regiao == "Nordeste").all() and "porcao_g" in d


def test_usuarios_local(tmp_path):
    cli = ClienteUsuarios(url=f"http://127.0.0.1:{_porta_livre()}", arquivo_local=tmp_path / "u.json")
    u = cli.criar("Ana", DADOS, regiao="Sul", restricoes=["vegetariano"])
    assert cli.local and u["id"] and cli.obter(u["id"])["regiao"] == "Sul"
    e1 = cli.registrar_escolha(u["id"], "almoco", 1, ["C0209A"])
    e2 = cli.registrar_escolha(u["id"], "jantar", 0, ["C0209A"])
    assert (e1["id"], e2["id"]) == (1, 2)
    assert [e["refeicao"] for e in cli.escolhas(u["id"], "almoco")] == ["almoco"]
    cli.salvar_estado_bandit(u["id"], {"almoco": {"A": [[1.0]], "b": [0.0]}})
    assert cli.obter(u["id"])["estado_bandit"]["almoco"]["b"] == [0.0]
    with pytest.raises(UsuarioNaoEncontrado):
        cli.obter("nao-existe")
    with pytest.raises(ValueError):
        cli.criar("Sem dados", {"sexo": "F"})


# ---------------------------------------------------------------- com os mocks do Mockoon
@pytest.mark.skipif(not KB_NO_AR, reason="mock da TBCA fora do ar (mocks/tbca.json, porta 3002)")
def test_kb_api():
    df = cliente_kb.buscar_alimentos("frango", limite=3)
    assert df.attrs["fonte"].startswith("API") and len(df) == 3
    assert cliente_kb.alimento("C0209A")["codigo"] == "C0209A"
    assert cliente_kb.alimento("NAO-EXISTE") is None
    api = cliente_kb.despensa(regiao="Nordeste", refeicao="almoco")
    assert len(api) == 45


@pytest.mark.skipif(not (KB_NO_AR and USUARIOS_NO_AR), reason="mocks da TBCA e de usuários fora do ar")
def test_cronograma_do_usuario_guarda_escolha_e_estado():
    cli = ClienteUsuarios()
    u = cli.criar("Teste", DADOS, regiao="Nordeste", restricoes=["sem_lactose"])
    assert not cli.local
    c = Cronograma.do_usuario(u["id"], cli, usar_api=False)
    c.opcoes("almoco")
    c.escolher("almoco", 1)
    escolhas = cli.escolhas(u["id"])
    assert len(escolhas) == 1 and escolhas[0]["posicao"] == 1 and len(escolhas[0]["codigos"]) == 5
    c2 = Cronograma.do_usuario(u["id"], cli, usar_api=False)       # outro dia: o estado volta da API
    assert np.allclose(c2.avaliador.modelos["almoco"][0], c.avaliador.modelos["almoco"][0])

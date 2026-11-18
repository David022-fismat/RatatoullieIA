"""
Testes do cronograma por ingredientes: calculadora DRI, API, cliente (com plano B), Montador e Avaliador.

    pip install pytest
    python -m pytest tests -q

O teste do contrato com o Mockoon só roda se houver uma API DRI no ar em DRI_API_URL (padrão
http://localhost:3001): suba o mock com  npx @mockoon/cli start --data mocks/dri.json  antes.
"""
import json
import os
import socket
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import numpy as np
import pytest

from agents.avaliador_ingredientes import AvaliadorIngredientes
from agents.calculadora_dri import REPARTICAO, ForaDoEscopo, calcular_dri
from agents.cliente_dri import PerfilRecusado, obter_metas
from agents.montador_ingredientes import MontadorIngredientes

MULHER = dict(sexo="F", idade=30, altura_cm=163, peso_kg=62, atividade="pouco_ativo")
HOMEM = dict(sexo="M", idade=35, altura_cm=175, peso_kg=78, atividade="ativo")


# ---------------------------------------------------------------- calculadora DRI
def test_eer_confere_com_a_tabela_s1():
    # mulher, pouco ativa: 575,77 − 7,01·30 + 6,60·163 + 12,14·62
    assert calcular_dri(**MULHER)["dia"]["energia_kcal"] == round(575.77 - 7.01 * 30 + 6.60 * 163 + 12.14 * 62)
    # homem, ativo: 1004,82 − 10,83·35 + 6,52·175 + 15,91·78
    assert calcular_dri(**HOMEM)["dia"]["energia_kcal"] == round(1004.82 - 10.83 * 35 + 6.52 * 175 + 15.91 * 78)


def test_macros_dentro_das_faixas():
    m = calcular_dri(**MULHER)
    kcal, d = m["dia"]["energia_kcal"], m["dia"]
    assert d["proteina_g"]["meta"] >= d["proteina_g"]["rda"] == round(0.8 * 62, 1)
    assert d["proteina_g"]["min"] <= d["proteina_g"]["meta"] <= d["proteina_g"]["max"]
    assert d["carboidrato_g"]["min"] <= d["carboidrato_g"]["meta"] <= d["carboidrato_g"]["max"]
    assert d["fibra_g"] == round(14 * kcal / 1000, 1)
    assert abs(sum(REPARTICAO.values()) - 1) < 1e-9
    assert sum(r["energia_kcal"] for r in m["refeicoes"].values()) == pytest.approx(kcal, abs=3)


@pytest.mark.parametrize("extra", [{"idade": 17}, {"gestante": True}, {"amamentando": True}])
def test_fora_do_escopo(extra):
    with pytest.raises(ForaDoEscopo):
        calcular_dri(**{**MULHER, **extra})


# ---------------------------------------------------------------- API real e cliente
def _porta_livre():
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture
def api_real(monkeypatch):
    from servicos.api_dri import Handler
    porta = _porta_livre()
    servidor = ThreadingHTTPServer(("127.0.0.1", porta), Handler)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    monkeypatch.setenv("DRI_API_URL", f"http://127.0.0.1:{porta}")
    yield f"http://127.0.0.1:{porta}"
    servidor.shutdown()


def test_api_real_devolve_o_mesmo_que_a_calculadora(api_real):
    metas = obter_metas(MULHER)
    assert metas["dia"] == calcular_dri(**MULHER)["dia"]


def test_api_real_recusa_menor_de_idade(api_real):
    with pytest.raises(PerfilRecusado):
        obter_metas({**MULHER, "idade": 15})


def test_cliente_usa_calculo_local_se_api_fora(monkeypatch):
    monkeypatch.setenv("DRI_API_URL", f"http://127.0.0.1:{_porta_livre()}")     # ninguém escutando
    metas = obter_metas(MULHER)
    assert metas["fonte"].startswith("cálculo local")
    assert metas["dia"]["energia_kcal"] == calcular_dri(**MULHER)["dia"]["energia_kcal"]


def _api_no_ar():
    url = os.getenv("DRI_API_URL", "http://localhost:3001")
    try:
        with urllib.request.urlopen(f"{url}/saude", timeout=1) as r:
            return json.loads(r.read()).get("status") == "ok"
    except Exception:
        return False


@pytest.mark.skipif(not _api_no_ar(), reason="nenhuma API DRI no ar (suba o Mockoon: mocks/dri.json)")
def test_contrato_do_mock_ou_da_api():
    metas = obter_metas(MULHER)
    for chave in ("imc", "dia", "refeicoes", "fonte"):
        assert chave in metas
    for r in ("cafe_da_manha", "almoco", "lanche", "jantar"):
        assert {"energia_kcal", "proteina_g", "fibra_g", "sodio_mg_max"} <= set(metas["refeicoes"][r])
    with pytest.raises(PerfilRecusado):
        obter_metas({**MULHER, "gestante": True})
    assert obter_metas(MULHER, cenario="erro")["fonte"].startswith("cálculo local")


# ---------------------------------------------------------------- Montador e Avaliador
@pytest.fixture(scope="module")
def metas():
    return calcular_dri(**MULHER)["refeicoes"]


def test_montador_bate_a_energia_e_a_proteina(metas):
    df = MontadorIngredientes(regiao="Nordeste").combinacoes("almoco", metas["almoco"])
    assert len(df) > 100
    assert np.median(np.abs(df.desvio_energia)) < 0.10
    prot = df.proteina_g / metas["almoco"]["proteina_g"]
    assert (prot >= 0.95).mean() > 0.8                           # a meta de proteína é um mínimo
    assert all(len(it) == 5 and all(i["gramas"] % 5 == 0 for i in it) for it in df.itens)


def test_trava_vegetariano_e_nao_gosta(metas):
    m = MontadorIngredientes(regiao="Sudeste")
    df = m.combinacoes("almoco", metas["almoco"])
    av = AvaliadorIngredientes(restricoes=["vegetariano"], nao_gosta=["tomate"])
    ops, resumo = av.tres_opcoes(df, "almoco", metas["almoco"])
    assert len(ops) == 3 and resumo["vetadas"] > 0
    for itens in ops.itens:
        for i in itens:
            assert "tomate" not in i["alimento"].lower()
            if i["grupo"] == "proteina":
                assert i["subtipo"] in ("leguminosa", "ovo", "leite", "queijo", "iogurte", "outro")


def test_tres_opcoes_variadas(metas):
    df = MontadorIngredientes(regiao="Nordeste").combinacoes("almoco", metas["almoco"])
    ops, _ = AvaliadorIngredientes().tres_opcoes(df, "almoco", metas["almoco"])
    cods = list(ops.codigos)
    assert all(len(cods[i] - cods[j]) >= 2 for i in range(3) for j in range(3) if i != j)


def test_bandit_aprende_o_gosto(metas):
    """Pessoa que sempre escolhe a opção com feijão (se houver): o maior peso aprendido é leguminosa."""
    df = MontadorIngredientes(regiao="Nordeste").combinacoes("almoco", metas["almoco"])
    av = AvaliadorIngredientes()
    for _ in range(15):
        ops, _ = av.tres_opcoes(df, "almoco", metas["almoco"])
        tem = [any(i["subtipo"] == "leguminosa" for i in it) for it in ops.itens]
        av.registrar_escolha("almoco", ops, tem.index(True) if any(tem) else 0)
    gosta, _ = av.explicar("almoco", top=1)
    assert gosta.index[0] == "proteina:leguminosa"
    estado = av.estado()
    novo = AvaliadorIngredientes()
    novo.carregar(json.loads(json.dumps(estado)))
    assert np.allclose(novo.modelos["almoco"][1], av.modelos["almoco"][1])

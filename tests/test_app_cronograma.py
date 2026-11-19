"""A página "Cronograma" do Streamlit: monta o dia sem cadastro, troca um alimento pelo SOM e escolhe.

    python -m pytest tests/test_app_cronograma.py -q
"""
from pathlib import Path

import pytest

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
APP = str(Path(__file__).resolve().parent.parent / "layout" / "cronograma_app.py")


def test_pagina_cronograma_sem_cadastro():
    at = AppTest.from_file(APP, default_timeout=180).run()
    assert not at.exception
    at.sidebar.radio[0].set_value("Sem cadastro").run()
    at.sidebar.selectbox(key="sem_regiao").set_value("Nordeste")
    next(b for b in at.sidebar.button if b.label == "Montar o dia").click().run()
    assert not at.exception and not at.error
    assert [t.label for t in at.tabs] == ["Café da manhã", "Almoço", "Lanche", "Jantar"]
    at.button(key="ach_almoco_0").click().run()
    trocas = [b for b in at.button if b.key and b.key.startswith("trc_almoco_0")]
    assert trocas
    antes = at.session_state["dia"]["refeicoes"]["almoco"]["opcoes"][0]["itens"][0]["alimento"]
    trocas[0].click().run()
    assert not at.exception and not at.error
    assert at.session_state["dia"]["refeicoes"]["almoco"]["opcoes"][0]["itens"][0]["alimento"] != antes
    at.button(key="esc_almoco_0").click().run()
    assert at.session_state["escolhidas"] == {"almoco": 0}

"""
Interface no navegador do RatatouilleIA.

    streamlit run app.py          (ou: streamlit run layout/app.py)

Abre uma página no navegador com:
  - o perfil na barra lateral;
  - "Planejar": estoque -> cardápio do Montador + Avaliador, retorno "eu faria" e lista de compras;
  - "Conversa": o Orquestrador (LLM) decidindo quais agentes chamar, com o rastro de decisões;
  - "Memória da semana": o que o Avaliador lembra, com um botão para simular os dias passando.
Tudo fica na sessão do navegador; só o botão "Salvar perfil" grava perfil.json.
"""
import json
import os
import re
from urllib.parse import quote_plus
from datetime import date, timedelta

import streamlit as st

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # pasta principal do projeto

from agents.agentes import ARQ_PERFIL, RESTRICOES, Perfil, salvar_perfil  # noqa: E402
from agents.memoria import MemoriaSemana  # noqa: E402
from agents.orquestrador import Orquestrador  # noqa: E402

st.set_page_config(page_title="RatatouilleIA", page_icon="🍲", layout="wide")

# chaves de API vindas do .streamlit/secrets.toml (ou do Streamlit Cloud), se houver
for var in ("GEMINI_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY"):
    try:
        if var in st.secrets and not os.getenv(var):
            os.environ[var] = st.secrets[var]
    except Exception:          # sem arquivo de secrets
        pass


# ------------------------------------------------------------------ vídeos (só um link de busca)
def link_youtube(nome):
    """Link de BUSCA no YouTube pelo nome da receita: não copia conteúdo de ninguém, não precisa de
    API nem de chave. '(adaptada: ...)' sai do nome para a busca achar o prato original."""
    base = re.sub(r"\s*\(adaptada:.*\)\s*$", "", nome).strip()
    return "https://www.youtube.com/results?search_query=" + quote_plus(f"{base} receita")


AVISO_VIDEO = "os vídeos podem usar ingredientes diferentes: confira as suas restrições"


def mostrar_video(nome):
    st.markdown(f"[🎥 Ver vídeos no YouTube]({link_youtube(nome)}) · _{AVISO_VIDEO}_")


# ------------------------------------------------------------------ estado da sessão
def novo_orquestrador():
    perfil = Perfil()
    if ARQ_PERFIL.exists():
        perfil = Perfil(**json.loads(ARQ_PERFIL.read_text(encoding="utf-8")))
    orq = Orquestrador(perfil=perfil, estoque={}, salvar=False)
    orq.memoria = MemoriaSemana(orq.ing, salvar=False)        # memória só desta sessão
    orq.avaliador.memoria = orq.memoria
    return orq


if "orq" not in st.session_state:
    st.session_state.orq = novo_orquestrador()
    st.session_state.plano = None
    st.session_state.chat = []
    st.session_state.dia = 0
orq = st.session_state.orq
orq.memoria.hoje = date.today() + timedelta(days=st.session_state.dia)
nomes = {i: x["nome"] for i, x in orq.ing.items()}
por_nome = {v: k for k, v in nomes.items()}

# ------------------------------------------------------------------ barra lateral: perfil
with st.sidebar:
    st.header("Seu perfil")
    p = orq.perfil
    if "w_restr" not in st.session_state:          # valores iniciais dos campos, só na 1ª vez
        st.session_state.update({"w_restr": list(p.restricoes), "w_pessoas": int(p.pessoas),
                                 "w_tempo": int(p.tempo_max_min),
                                 "w_regiao": p.regiao if p.regiao in ("Norte", "Nordeste", "Centro-Oeste",
                                                                      "Sudeste", "Sul") else "Brasil",
                                 "w_gosta": [nomes[i] for i in p.gosta if i in nomes],
                                 "w_nao": [nomes[i] for i in p.nao_gosta if i in nomes]})
    p.restricoes = st.multiselect("Restrições (regras de segurança)", RESTRICOES, key="w_restr")
    p.pessoas = st.number_input("Pessoas", 1, 12, key="w_pessoas")
    p.tempo_max_min = st.slider("Tempo máximo (min)", 10, 120, step=5, key="w_tempo")
    regioes = ["Brasil", "Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul"]
    p.regiao = st.selectbox("Região", regioes, key="w_regiao")
    gosta = st.multiselect("Gosta de", sorted(por_nome), key="w_gosta")
    nao_gosta = st.multiselect("Não gosta de", sorted(por_nome), key="w_nao")
    p.gosta, p.nao_gosta = [por_nome[n] for n in gosta], [por_nome[n] for n in nao_gosta]
    if st.button("Salvar perfil"):
        salvar_perfil(p)
        st.success("Perfil salvo em perfil.json")
    with st.expander("Pesos que o agente aprendeu"):
        st.caption("Quanto cada critério pesa na nota. Mudam a cada opção que você escolhe.")
        st.bar_chart({k: round(v, 2) for k, v in p.pesos.items()
                      if k not in ("regiao", "usa_estoque", "tem_em_casa")})

st.title("RatatouilleIA")
st.caption(f"Dia simulado: {orq.memoria.hoje.strftime('%d/%m/%Y')}")
aba_plan, aba_chat, aba_mem = st.tabs(["Planejar", "Conversa com o agente", "Memória da semana"])

# ------------------------------------------------------------------ aba: planejar (opções)
def pedir_opcoes(outras=False):
    with st.spinner("Montador propondo, Avaliador avaliando..."):
        st.session_state.plano = orq.opcoes_de_refeicao(n=int(st.session_state.get("w_n", 4)),
                                                        outras_opcoes=outras)
    st.session_state.escolha = None


with aba_plan:
    c1, c2 = st.columns([1, 3])
    c1.number_input("Quantas opções", 2, 8, 4, key="w_n")
    c2.write("")
    c2.caption("O sistema mostra opções diferentes entre si, respeitando o seu perfil. "
               "Escolha uma: ele aprende com a sua escolha e lembra dela durante a semana.")
    if st.button("Me dê opções de refeição", type="primary"):
        pedir_opcoes()

    plano = st.session_state.plano
    if plano:
        escolha = st.session_state.get("escolha")
        st.subheader(f"{plano['encontradas']} opções")
        with st.expander("Como o Montador e o Avaliador chegaram aqui"):
            st.write(f"Rodadas do laço Montador ↔ Avaliador: {plano['rodadas_montador_avaliador']}")
            if plano["motivos_de_rejeicao"]:
                st.write("Motivos de rejeição devolvidos ao Montador:")
                for m in plano["motivos_de_rejeicao"]:
                    st.write(f"- {m}")
            else:
                st.write("Nenhuma receita rejeitada.")
        for r in plano["opcoes"]:
            escolhida = bool(escolha) and escolha["escolhida"] == r["nome"]
            with st.container(border=True):
                a, b, c, d = st.columns([4, 1, 1, 1])
                a.markdown(f"**{r['numero']}. {r['nome']}**" + ("  ✅ escolhida" if escolhida else ""))
                b.metric("Tempo", f"{r['tempo_min']} min")
                c.metric("Nota", f"{r['nota']:.2f}")
                d.metric("kcal/pessoa", f"{r['por_pessoa']['kcal']:.0f}")
                st.write(f"**Por quê:** {r['por_que']}")
                st.write("**Ingredientes:** " + ", ".join(f"{i} {g} g" for i, g in r["ingredientes"].items()))
                if r.get("preparo"):
                    with st.expander("Modo de preparo", expanded=escolhida):
                        st.text(r["preparo"])
                mostrar_video(r["nome"])
                if not escolha and st.button("Quero esta", key=f"quero_{r['numero']}_{r['nome']}"):
                    st.session_state.escolha = orq.escolher_receita(r["nome"])
                    st.rerun()
        if escolha:
            mud = escolha.get("pesos_que_mudaram", {})
            aprendeu = ("; pesos que mudaram: " + ", ".join(f"{k} {a} → {b}" for k, (a, b) in mud.items())
                        if mud else "")
            st.success(f"Boa escolha: {escolha['escolhida']}. O agente aprendeu com ela{aprendeu}. "
                       "Ela entra na memória da semana, para não repetir.")
        b1, b2 = st.columns(2)
        if b1.button("Outras opções"):
            pedir_opcoes(outras=True)
            st.rerun()
        if b2.button("Avançar 1 dia e pedir opções de novo"):
            st.session_state.dia += 1
            orq.memoria.hoje = date.today() + timedelta(days=st.session_state.dia)
            pedir_opcoes()
            st.rerun()

# ------------------------------------------------------------------ aba: conversa
with aba_chat:
    from agents.provedores import criar_cliente, provedor_disponivel
    provedor = provedor_disponivel()
    if provedor is None and not st.session_state.get("chave_gemini"):
        st.info("Para conversar, cole uma chave grátis do Gemini (aistudio.google.com/apikey). "
                "Ela fica só nesta sessão do navegador e não é salva.")
        chave = st.text_input("Chave do Gemini", type="password")
        if chave:
            st.session_state.chave_gemini = chave.strip()
            st.rerun()
    else:
        if orq.cliente is None:
            if provedor is None:                  # chave colada na tela: só desta sessão
                provedor = "gemini"
                orq.cliente, orq.modelo = criar_cliente("gemini", chave=st.session_state.chave_gemini)
            else:
                orq.cliente, orq.modelo = criar_cliente(provedor)
        provedor = provedor or "gemini"
        ativo = getattr(orq.cliente, "modelo_ativo", None) or orq.modelo
        st.caption(f"LLM: {provedor}, modelo {ativo}. Cada mensagem pode levar alguns segundos; "
                   "se um modelo estiver sobrecarregado, o agente troca para um reserva sozinho.")
        for msg in st.session_state.chat:
            with st.chat_message(msg["papel"]):
                st.write(msg["texto"])
                for nome, preparo in msg.get("preparos", {}).items():
                    with st.expander(f"Como fazer: {nome}"):   # vem da base, não depende do LLM
                        if preparo:
                            st.text(preparo)
                        else:
                            st.caption("Esta receita ainda não tem modo de preparo escrito na base.")
                        mostrar_video(nome)
                if msg.get("decisoes"):
                    with st.expander("Decisões do agente"):
                        for d in msg["decisoes"]:
                            if "ferramenta" in d:
                                st.code(f"{d['passo']}. {d['ferramenta']}({d['argumentos']}) -> {d['resultado']}")
                            else:
                                st.code(d["decisao"])
        pedido = st.chat_input("Ex.: comprei frango e tomate, tô sem tempo, o que faço hoje?")
        if pedido:
            st.session_state.chat.append({"papel": "user", "texto": pedido})
            with st.spinner("O agente está decidindo..."):
                try:
                    resposta = orq.responder(pedido)
                except Exception as e:
                    resposta, orq.decisoes, orq.preparos = f"Erro ao falar com o LLM: {e}", [], {}
            st.session_state.chat.append({"papel": "assistant", "texto": resposta,
                                          "decisoes": list(orq.decisoes),
                                          "preparos": dict(getattr(orq, "preparos", {}))})
            st.rerun()

# ------------------------------------------------------------------ aba: memória
with aba_mem:
    st.write("O Avaliador lembra o que você escolheu nos últimos 7 dias e tira pontos do que se repete. "
             "Use 'Avançar 1 dia' para ver as opções mudarem com o mesmo pedido.")
    m1, m2, m3 = st.columns(3)
    if m1.button("Avançar 1 dia"):
        st.session_state.dia += 1
        st.rerun()
    if m2.button("Voltar para hoje"):
        st.session_state.dia = 0
        st.rerun()
    if m3.button("Apagar memória"):
        orq.memoria.limpar()
        st.rerun()
    recentes = orq.memoria.recentes()
    if recentes:
        st.table([{"dia": "/".join(reversed(e["data"].split("-")[1:])), "receita": e["nome"]}
                  for e in reversed(recentes)])
    else:
        st.write("Nada escolhido nos últimos 7 dias.")

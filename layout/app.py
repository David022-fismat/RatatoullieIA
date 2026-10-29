"""
Interface no navegador do RatatouilleIA.

    streamlit run app.py

Abre uma página no navegador com:
  - o perfil na barra lateral;
  - "Planejar": estoque -> cardápio do Montador + Avaliador, retorno "eu faria" e lista de compras;
  - "Conversa": o Orquestrador (LLM) decidindo quais agentes chamar, com o rastro de decisões;
  - "Memória da semana": o que o Avaliador lembra, com um botão para simular os dias passando.
Tudo fica na sessão do navegador; só o botão "Salvar perfil" grava perfil.json.
"""
import json
import os
from datetime import date, timedelta

import streamlit as st

from agente_interativo import ARQ_PERFIL, RESTRICOES, salvar_perfil
from agentes import Perfil
from memoria import MemoriaSemana
from orquestrador import Orquestrador

st.set_page_config(page_title="RatatouilleIA", page_icon="🍲", layout="wide")

# chaves de API vindas do .streamlit/secrets.toml (ou do Streamlit Cloud), se houver
for var in ("GEMINI_API_KEY", "GROQ_API_KEY", "ANTHROPIC_API_KEY"):
    try:
        if var in st.secrets and not os.getenv(var):
            os.environ[var] = st.secrets[var]
    except Exception:          # sem arquivo de secrets
        pass


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
                                 "w_gosta": [nomes[i] for i in p.gosta if i in nomes],
                                 "w_nao": [nomes[i] for i in p.nao_gosta if i in nomes]})
    p.restricoes = st.multiselect("Restrições (regras de segurança)", RESTRICOES, key="w_restr")
    p.pessoas = st.number_input("Pessoas", 1, 12, key="w_pessoas")
    p.tempo_max_min = st.slider("Tempo máximo (min)", 10, 120, step=5, key="w_tempo")
    gosta = st.multiselect("Gosta de", sorted(por_nome), key="w_gosta")
    nao_gosta = st.multiselect("Não gosta de", sorted(por_nome), key="w_nao")
    p.gosta, p.nao_gosta = [por_nome[n] for n in gosta], [por_nome[n] for n in nao_gosta]
    if st.button("Salvar perfil"):
        salvar_perfil(p)
        st.success("Perfil salvo em perfil.json")
    with st.expander("Pesos que o agente aprendeu"):
        st.caption("Quanto cada critério pesa na nota. Mudam com o retorno 'eu faria'.")
        st.bar_chart({k: round(v, 2) for k, v in p.pesos.items() if k != "regiao"})

st.title("RatatouilleIA")
st.caption(f"Dia simulado: {orq.memoria.hoje.strftime('%d/%m/%Y')}")
aba_plan, aba_chat, aba_mem = st.tabs(["Planejar", "Conversa com o agente", "Memória da semana"])

# ------------------------------------------------------------------ aba: planejar
with aba_plan:
    c1, c2 = st.columns([3, 1])
    texto = c1.text_input("O que você tem em casa? (ex.: ovo 600, tomate, abobrinha 300g)",
                          value=", ".join(f"{nomes[i]} {g:.0f}" for i, g in orq.estoque.items()
                                          if i not in ("oleo", "alho", "cebola", "arroz")))
    n = c2.number_input("Refeições", 1, 14, 3)
    despensa = st.checkbox("Tenho o básico de despensa (óleo, alho, cebola, arroz)", value=True)

    if st.button("Montar cardápio", type="primary"):
        orq.estoque = {}
        itens = []
        for parte in filter(None, (x.strip() for x in texto.split(","))):
            palavras = parte.split()
            ultimo = palavras[-1].lower().rstrip("g")
            if ultimo.isdigit() and len(palavras) > 1:
                itens.append({"nome": " ".join(palavras[:-1]), "gramas": int(ultimo)})
            else:
                itens.append({"nome": parte})
        if despensa:
            itens += [{"nome": x, "gramas": 1000} for x in ("óleo de soja", "alho", "cebola", "arroz branco")]
        lido = orq.atualizar_estoque(adicionar=itens)
        if lido["nao_existem_na_base"]:
            st.warning("Não reconheci: " + ", ".join(lido["nao_existem_na_base"]) + " (ficou de fora)")
        with st.spinner("Montador propondo, Avaliador avaliando..."):
            st.session_state.plano = orq.planejar_refeicoes(n=int(n))
        st.session_state.retorno = None

    plano = st.session_state.plano
    if plano:
        st.subheader(f"Cardápio: {plano['encontradas']} de {plano['pedidas']} receitas")
        with st.expander("Como o Montador e o Avaliador chegaram aqui"):
            st.write(f"Rodadas do laço Montador ↔ Avaliador: {plano['rodadas_montador_avaliador']}")
            if plano["motivos_de_rejeicao"]:
                st.write("Motivos de rejeição devolvidos ao Montador:")
                for m in plano["motivos_de_rejeicao"]:
                    st.write(f"- {m}")
            else:
                st.write("Nenhuma receita rejeitada.")
        feitas = []
        for k, r in enumerate(plano["receitas"]):
            with st.container(border=True):
                a, b, c, d = st.columns([4, 1, 1, 1])
                a.markdown(f"**{r['nome']}**")
                b.metric("Tempo", f"{r['tempo_min']} min")
                c.metric("Nota", f"{r['nota']:.2f}")
                d.metric("kcal/pessoa", f"{r['por_pessoa']['kcal']:.0f}")
                st.write(f"**Por quê:** {r['por_que']}")
                st.write("**Ingredientes:** " + ", ".join(f"{i} {g} g" for i, g in r["ingredientes"].items()))
                st.write("**Falta comprar:** " + (", ".join(r["falta_comprar"]) or "nada, você tem tudo"))
                if st.checkbox("Eu faria esta", key=f"fiz_{k}_{r['nome']}"):
                    feitas.append(r["nome"])
        b1, b2, b3 = st.columns(3)
        if b1.button("Registrar retorno (o agente aprende)"):
            st.session_state.retorno = orq.registrar_retorno(feitas)
        if b2.button("Lista de compras"):
            lista = orq.lista_de_compras()
            st.session_state.lista = lista
        if b3.button("Avançar 1 dia e planejar de novo"):
            st.session_state.dia += 1
            st.session_state.retorno = None
            orq.memoria.hoje = date.today() + timedelta(days=st.session_state.dia)
            st.session_state.plano = orq.planejar_refeicoes(n=int(n))
            st.rerun()
        if st.session_state.get("retorno"):
            mud = st.session_state.retorno.get("pesos_que_mudaram", {})
            st.info("Pesos ajustados: " + (", ".join(f"{k}: {a} → {b}" for k, (a, b) in mud.items())
                                           or "nenhuma mudança"))
        if st.session_state.get("lista"):
            lista = st.session_state.lista
            if "itens" in lista:
                st.write(f"**Lista de compras** (estimativa R$ {lista['total_estimado_reais']:.2f}; "
                         "preços estimados pelo grupo)")
                st.table([{"item": x["item"], "embalagens": x["embalagens"],
                           "R$": f"{x['custo_estimado']:.2f}"} for x in lista["itens"]])

# ------------------------------------------------------------------ aba: conversa
with aba_chat:
    from provedores import criar_cliente, provedor_disponivel
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
                if msg.get("decisoes"):
                    with st.expander("Decisões do agente"):
                        for d in msg["decisoes"]:
                            if "ferramenta" in d:
                                st.code(f"{d['passo']}. {d['ferramenta']}({d['argumentos']}) -> {d['resultado']}")
                            else:
                                st.code(d["decisao"])
        seco = st.toggle("Modo teste: só mostrar qual ferramenta ele escolheria, sem executar")
        pedido = st.chat_input("Ex.: comprei frango e tomate, tô sem tempo, o que faço hoje?")
        if pedido:
            st.session_state.chat.append({"papel": "user", "texto": pedido})
            with st.spinner("O agente está decidindo..."):
                try:
                    if seco:
                        escolhas = orq.decidir(pedido)
                        resposta = "**[modo teste]** Escolheria: " + "; ".join(
                            f"`{d['ferramenta']}({json.dumps(d['argumentos'], ensure_ascii=False)})`"
                            for d in escolhas)
                        orq.decisoes = []
                    else:
                        resposta = orq.responder(pedido)
                except Exception as e:
                    resposta, orq.decisoes = f"Erro ao falar com o LLM: {e}", []
            st.session_state.chat.append({"papel": "assistant", "texto": resposta,
                                          "decisoes": list(orq.decisoes)})
            st.rerun()

# ------------------------------------------------------------------ aba: memória
with aba_mem:
    st.write("O Avaliador lembra o que foi sugerido nos últimos 7 dias e tira pontos do que se repete. "
             "Use 'Avançar 1 dia' para ver o cardápio mudar com o mesmo pedido.")
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
        st.write("Nada sugerido nos últimos 7 dias.")

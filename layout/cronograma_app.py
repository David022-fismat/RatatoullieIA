"""
Página "Cronograma" do app: o dia montado com ingredientes, 3 opções por refeição, troca pelo mapa SOM.

    streamlit run app.py                       (aparece no menu lateral como "Cronograma")
    streamlit run layout/cronograma_app.py     (só esta página)

De onde vêm os dados (cada um com plano B se a API não responder):
    metas DRI       DRI_API_URL       (mock: mocks/dri.json, porta 3001)       -> cálculo local
    despensa/TBCA   KB_API_URL        (mock: mocks/tbca.json, porta 3002)      -> arquivos de kb/
    usuários        USUARIOS_API_URL  (mock: mocks/usuarios.json, porta 3003)  -> usuarios_local.json
Para subir os mocks:  npx @mockoon/cli start --data mocks/dri.json mocks/tbca.json mocks/usuarios.json
"""
import re
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # pasta principal do projeto

from agents.cliente_dri import PerfilRecusado              # noqa: E402
from agents.cliente_usuarios import ClienteUsuarios, UsuarioNaoEncontrado   # noqa: E402
from agents.cronograma import ROTULO_GRUPO, Cronograma      # noqa: E402
from agents.montador_ingredientes import GRUPOS_REFEICAO, NOMES_REFEICAO   # noqa: E402
from agents.substituidor import RESTRICAO                   # noqa: E402

st.set_page_config(page_title="RatatouilleIA · Cronograma", page_icon="🗓️", layout="wide")

REGIOES = ["Brasil", "Norte", "Nordeste", "Centro-Oeste", "Sudeste", "Sul"]
ATIVIDADES = {"inativo": "Inativo (quase sem exercício)", "pouco_ativo": "Pouco ativo",
              "ativo": "Ativo", "muito_ativo": "Muito ativo"}
ROTULO_RESTRICAO = {"vegetariano": "Vegetariano", "sem_lactose": "Sem lactose", "alergia_ovo": "Alergia a ovo",
                    "celiaco": "Celíaco (sem glúten)", "sem_carne_vermelha": "Sem carne vermelha"}
GRUPO_DO_ROTULO = {v: k for k, v in ROTULO_GRUPO.items()}
LATIM = re.compile(r"^[A-Z][a-z]+ [a-z]+( [A-Z(].*)?$|\bspp?\.?$|\bL\.$")    # nome científico no fim


PREPARO = re.compile(r"cozid|grelhad|assad|frit|refogad|crua?\b|crus\b|in natura|ensopad|vapor|empanad|drenad")


def nome_curto(descricao, termos=3):
    """'Carne, frango, peito, s/ pele, grelhado, ..., Gallus gallus' -> 'Carne, frango, peito, grelhado'.
    Os primeiros termos e o preparo (se vier depois); o nome científico do fim sai. Vírgulas dentro de
    parênteses não separam termos."""
    partes = [p.strip() for p in re.split(r",(?![^()]*\))", descricao) if p.strip()]
    while len(partes) > 1 and LATIM.search(partes[-1]):
        partes.pop()
    curto = partes[:termos]
    if not any(PREPARO.search(p.lower()) for p in curto):
        curto += [p for p in partes[termos:] if PREPARO.search(p.lower())][:1]
    return ", ".join(curto)


# ------------------------------------------------------------------ estado da sessão
ss = st.session_state
for chave, valor in {"cron": None, "usuario": None, "cli": None, "dia": None, "escolhidas": {},
                     "subs": {}, "aviso": None}.items():
    ss.setdefault(chave, valor)


def iniciar(cron, usuario=None, cli=None):
    ss.cron, ss.usuario, ss.cli = cron, usuario, cli
    ss.escolhidas, ss.subs = {}, {}
    ss.dia = cron.dia()


def formulario_perfil(prefixo):
    """Campos de perfil; devolve (nome, dados_dri, regiao, restricoes, nao_gosta)."""
    nome = st.text_input("Nome", key=f"{prefixo}_nome") if prefixo == "cad" else ""
    c1, c2 = st.columns(2)
    sexo = c1.selectbox("Sexo", ["F", "M"], key=f"{prefixo}_sexo",
                        format_func=lambda s: "Feminino" if s == "F" else "Masculino")
    idade = c2.number_input("Idade", 19, 110, 30, key=f"{prefixo}_idade")
    c3, c4 = st.columns(2)
    altura = c3.number_input("Altura (cm)", 120, 230, 165, key=f"{prefixo}_altura")
    peso = c4.number_input("Peso (kg)", 35.0, 250.0, 65.0, step=0.5, key=f"{prefixo}_peso")
    atividade = st.selectbox("Atividade física", list(ATIVIDADES), index=1, key=f"{prefixo}_ativ",
                             format_func=ATIVIDADES.get)
    regiao = st.selectbox("Região", REGIOES, key=f"{prefixo}_regiao")
    restricoes = st.multiselect("Restrições", list(RESTRICAO), key=f"{prefixo}_restr",
                                format_func=lambda r: ROTULO_RESTRICAO.get(r, r))
    nao_gosta = st.text_input("Não gosta de (separe por vírgula)", key=f"{prefixo}_nao")
    dados = {"sexo": sexo, "idade": int(idade), "altura_cm": float(altura), "peso_kg": float(peso),
             "atividade": atividade}
    return nome, dados, regiao, restricoes, [x.strip() for x in nao_gosta.split(",") if x.strip()]


# ------------------------------------------------------------------ barra lateral: quem é a pessoa
with st.sidebar:
    st.header("Quem é você?")
    modo = st.radio("modo", ["Entrar com meu ID", "Cadastrar", "Sem cadastro"], label_visibility="collapsed")
    try:
        if modo == "Entrar com meu ID":
            uid = st.text_input("ID do usuário", value="exemplo",
                                help="O mock de usuários já vem com o usuário 'exemplo'.")
            if st.button("Entrar", type="primary", use_container_width=True):
                cli = ClienteUsuarios()
                iniciar(Cronograma.do_usuario(uid.strip(), cli), cli.obter(uid.strip()), cli)
        elif modo == "Cadastrar":
            with st.form("cadastro"):
                nome, dados, regiao, restricoes, nao_gosta = formulario_perfil("cad")
                ok = st.form_submit_button("Cadastrar e montar o dia", type="primary", use_container_width=True)
            if ok:
                cli = ClienteUsuarios()
                u = cli.criar(nome or "Sem nome", dados, regiao=regiao, restricoes=restricoes, nao_gosta=nao_gosta)
                iniciar(Cronograma.do_usuario(u["id"], cli), u, cli)
                ss.aviso = f"Cadastro feito. Guarde seu ID para voltar outro dia: `{u['id']}`"
        else:
            with st.form("sem_cadastro"):
                _, dados, regiao, restricoes, nao_gosta = formulario_perfil("sem")
                ok = st.form_submit_button("Montar o dia", type="primary", use_container_width=True)
            if ok:
                iniciar(Cronograma(dados, restricoes=restricoes, nao_gosta=nao_gosta, regiao=regiao))
    except PerfilRecusado as e:
        st.error(f"Não dá para montar o cronograma: {e}")
    except UsuarioNaoEncontrado:
        st.error("Não achei esse ID. Confira ou faça um cadastro.")

    if ss.cron is not None:
        st.divider()
        if ss.usuario:
            st.caption(f"Usuário: **{ss.usuario.get('nome', '')}**")
            st.code(ss.usuario["id"], language=None)
        c = ss.cron
        st.caption("De onde vêm os dados")
        st.caption(f"• metas: {c.metas.get('fonte')}")
        st.caption(f"• alimentos: {getattr(c, 'fonte_despensa', None) or 'arquivo local kb/cronograma/despensa.csv'}")
        if ss.cli:
            st.caption(f"• usuários: {ss.cli.fonte}")

# ------------------------------------------------------------------ página principal
st.title("🗓️ Cronograma do dia")
if ss.cron is None:
    st.info("Escolha na barra lateral: entre com seu ID, faça um cadastro ou monte um dia sem cadastro.")
    st.caption("Cada refeição traz 3 opções montadas com ingredientes, com as quantidades calculadas para as "
               "suas metas (calculadora DRI). Ao escolher, o agente aprende o que você prefere.")
    st.stop()

cron, dia = ss.cron, ss.dia
if ss.aviso:
    st.success(ss.aviso)
for aviso in dia.get("avisos", []):
    st.warning(aviso)

d = cron.metas["dia"]
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Energia do dia", f"{d['energia_kcal']} kcal")
m2.metric("Proteína (mínimo)", f"{d['proteina_g']['meta']:.0f} g")
m3.metric("Carboidrato", f"{d['carboidrato_g']['meta']:.0f} g")
m4.metric("Fibra", f"{d['fibra_g']:.0f} g")
m5.metric("Sódio (máximo)", f"{d['sodio_mg_max']} mg")


def mostrar_opcao(refeicao, k, op, metas):
    escolhida = ss.escolhidas.get(refeicao)
    titulo = f"Opção {k + 1}" + ("  ✅ escolhida" if escolhida == k else "")
    with st.container(border=True):
        st.markdown(f"**{titulo}**")
        st.markdown("\n".join(f"- **{i['gramas']:.0f} g** {nome_curto(i['alimento'])}  \n"
                               f"  <small>{i['grupo']}</small>" for i in op["itens"]), unsafe_allow_html=True)
        t, p = op["totais"], op["percentual_da_meta"]
        st.caption(f"{t['energia_kcal']:.0f} kcal ({p['energia']}% da meta) · proteína {t['proteina_g']:.0f} g "
                   f"({p['proteina']}%) · fibra {t['fibra_g']:.0f} g · sódio {t['sodio_mg']:.0f} mg")
        st.progress(min(op["bem_estar"], 1.0), text=f"bem-estar {op['bem_estar']:.2f}")
        with st.expander("Ver descrição completa (TBCA)"):
            for i in op["itens"]:
                st.caption(f"**{i['grupo']}** · {i['gramas']:.0f} g · {i['alimento']}")
        if st.button("Escolher esta", key=f"esc_{refeicao}_{k}", disabled=escolhida is not None,
                     use_container_width=True, type="primary"):
            cron.escolher(refeicao, k)
            ss.escolhidas[refeicao] = k
            st.rerun()
        painel_troca(refeicao, k, op, escolhida is not None)


def painel_troca(refeicao, k, op, travado):
    with st.expander("🔄 Trocar um alimento (mapa SOM)"):
        grupos = [i["grupo"] for i in op["itens"]]
        rotulo = st.selectbox("Qual?", grupos, key=f"grp_{refeicao}_{k}",
                              format_func=lambda g: f"{g}: {nome_curto(next(i['alimento'] for i in op['itens'] if i['grupo'] == g), 2)}")
        grupo = GRUPO_DO_ROTULO[rotulo]
        chave = (refeicao, k, grupo)
        if st.button("Achar substitutos", key=f"ach_{refeicao}_{k}", disabled=travado):
            ss.subs[chave] = cron.substitutos(refeicao, k, grupo)
        res = ss.subs.get(chave)
        if not res:
            if travado:
                st.caption("Esta refeição já foi escolhida.")
            return
        if not res["substitutos"]:
            st.caption("Nenhum substituto passou nas suas restrições.")
        if res.get("barrados_pela_trava"):
            st.caption(f"{res['barrados_pela_trava']} parecidos ficaram de fora porque a opção passaria do limite "
                       "(sódio) ou bateria numa restrição.")
        for j, x in enumerate(res["substitutos"]):
            n = x["por_100g"]
            st.markdown(f"**{x['gramas']:.0f} g {nome_curto(x['nome'])}**"
                        + ("  · _comum nessa refeição_" if x["comum"] else ""))
            st.caption(f"{x['motivo']} · por 100 g: {n['kcal']} kcal, {n['proteina_g']} g proteína, "
                       f"{n['fibra_g']} g fibra · bem-estar da opção ficaria {x['bem_estar_depois']:.2f}")
            if st.button(f"Trocar por este", key=f"trc_{refeicao}_{k}_{grupo}_{j}", disabled=travado,
                         use_container_width=True):
                try:
                    nova = cron.trocar(refeicao, k, grupo, x["codigo"])
                    ss.dia["refeicoes"][refeicao]["opcoes"][k] = nova
                    ss.subs.pop(chave, None)
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))


abas = st.tabs([NOMES_REFEICAO[r] for r in cron.refeicoes])
for aba, refeicao in zip(abas, cron.refeicoes):
    with aba:
        r = dia["refeicoes"][refeicao]
        metas, a = r["metas"], r["avaliacao"]
        st.markdown(f"**Meta:** {metas['energia_kcal']} kcal · proteína ≥ {metas['proteina_g']:.0f} g · "
                    f"fibra {metas['fibra_g']:.0f} g · sódio ≤ {metas['sodio_mg_max']} mg  \n"
                    f"<small>{a['combinacoes']} combinações de "
                    f"{' + '.join(ROTULO_GRUPO[g].lower() for g in GRUPOS_REFEICAO[refeicao])}; "
                    f"{a['vetadas']} vetadas (restrições, não gosta ou sódio); {a.get('saudaveis', 0)} na metade mais saudável"
                    f"</small>", unsafe_allow_html=True)
        if not r["opcoes"]:
            st.warning("Nenhuma combinação passou nas suas restrições.")
            continue
        colunas = st.columns(len(r["opcoes"]))
        for k, (col, op) in enumerate(zip(colunas, r["opcoes"])):
            with col:
                mostrar_opcao(refeicao, k, op, metas)
        if refeicao in ss.escolhidas:
            if st.button("Ver novas opções para amanhã", key=f"novas_{refeicao}"):
                ss.dia["refeicoes"][refeicao] = cron.opcoes(refeicao)
                ss.escolhidas.pop(refeicao)
                ss.subs = {k: v for k, v in ss.subs.items() if k[0] != refeicao}
                st.rerun()

st.divider()
c1, c2 = st.columns(2)
with c1.expander("🧠 O que o agente já aprendeu sobre você"):
    algum = False
    for refeicao in cron.refeicoes:
        if refeicao in cron.avaliador.modelos:
            gosta, evita = cron.avaliador.explicar(refeicao, 3)
            if abs(gosta).max() + abs(evita).max() < 1e-6:
                continue
            algum = True
            st.markdown(f"**{NOMES_REFEICAO[refeicao]}**: tende a escolher "
                        + ", ".join(f"{i} ({v:+.2f})" for i, v in gosta.items())
                        + "; tende a evitar " + ", ".join(f"{i} ({v:+.2f})" for i, v in evita.items()))
    if not algum:
        st.caption("Ainda nada: escolha algumas opções.")
if ss.usuario and ss.cli:
    with c2.expander("📒 Histórico de escolhas"):
        historico = ss.cli.escolhas(ss.usuario["id"])
        if historico:
            st.dataframe(pd.DataFrame(historico)[["data", "refeicao", "posicao", "codigos"]],
                         hide_index=True, use_container_width=True)
        else:
            st.caption("Nenhuma escolha registrada ainda.")

"""
Cronograma do dia por ingredientes: junta calculadora DRI (via API ou Mockoon), Montador e Avaliador.

    from agents.cronograma import Cronograma
    c = Cronograma({"sexo": "F", "idade": 30, "altura_cm": 163, "peso_kg": 62, "atividade": "pouco_ativo"},
                   restricoes=["sem_lactose"], regiao="Nordeste")
    dia = c.dia()                       # metas + 3 opções para cada refeição
    c.escolher("almoco", 1)             # a pessoa escolheu a 2ª opção do almoço: o bandit aprende

Trocar um alimento de uma opção pelo mapa SOM (agents/substituidor.py):
    c.substitutos("almoco", 0, "proteina")            # alimentos parecidos com a proteína da 1ª opção
    c.trocar("almoco", 0, "proteina", "C0029F")       # troca, recalcula gramas, nutrientes e bem-estar

Com um usuário cadastrado (API de usuários, mock em mocks/usuarios.json):
    c = Cronograma.do_usuario("exemplo")   # perfil e estado do bandit vêm da API; a despensa, da API da TBCA
    c.dia()
    c.escolher("almoco", 1)                # registra a escolha e salva o estado do bandit na API

Fluxo de cada refeição:
    calculadora DRI (metas da refeição) -> Montador (todas as combinações, gramas ajustadas às metas)
    -> Avaliador (trava, bem-estar, bandit) -> 3 opções
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from . import cliente_kb
from .avaliador_ingredientes import AvaliadorIngredientes
from .cliente_dri import obter_metas
from .cliente_usuarios import ClienteUsuarios
from .montador_ingredientes import (ARQ_DESPENSA, GRUPOS_REFEICAO, NOMES_REFEICAO, MontadorIngredientes,
                                    sem_acento, serve_no_prato, subtipo)

GENERICOS = {"carne", "peixe", "pao", "farinha", "biscoito", "queijo", "leite", "iogurte", "bebida", "oleo"}
ROTULO_GRUPO = {"proteina": "Proteína", "carboidrato": "Carboidrato", "leguminosa": "Leguminosa", "legumes": "Legumes",
                "fruta": "Fruta"}


class Cronograma:
    def __init__(self, dados_dri: dict, restricoes=(), nao_gosta=(), regiao: str = "Brasil",
                 usar_api: bool = True, estado_bandit: dict | None = None, despensa=None):
        self.metas = obter_metas(dados_dri, usar_api=usar_api)      # pode levantar PerfilRecusado
        self.montador = MontadorIngredientes(despensa, regiao=regiao)
        self.avaliador = AvaliadorIngredientes(restricoes, nao_gosta)
        self.avaliador.carregar(estado_bandit)
        self._combinacoes = {}
        self.mostradas = {}
        self.usuario_id = None
        self.usuarios = None
        self._som = None

    @classmethod
    def do_usuario(cls, usuario_id: str, usuarios: ClienteUsuarios | None = None, usar_api: bool = True):
        """Monta o cronograma de um usuário cadastrado: perfil e estado do bandit vêm da API de usuários,
        a despensa vem da API da base de conhecimento (com plano B nos arquivos locais)."""
        usuarios = usuarios or ClienteUsuarios()
        u = usuarios.obter(usuario_id)                                  # UsuarioNaoEncontrado se não existe
        regiao = u.get("regiao") or "Brasil"
        despensa = cliente_kb.despensa(regiao=regiao)
        if despensa.empty:
            regiao, despensa = "Brasil", cliente_kb.despensa(regiao="Brasil")
        c = cls(u["dados_dri"], restricoes=u.get("restricoes", []), nao_gosta=u.get("nao_gosta", []),
                regiao=regiao, usar_api=usar_api, estado_bandit=u.get("estado_bandit"), despensa=despensa)
        c.usuario_id, c.usuarios = usuario_id, usuarios
        c.fonte_despensa = despensa.attrs.get("fonte")
        return c

    @property
    def refeicoes(self):
        return [r for r in GRUPOS_REFEICAO if r in self.metas["refeicoes"]]

    def opcoes(self, refeicao: str, politica: str = "bandit") -> dict:
        metas = self.metas["refeicoes"][refeicao]
        if refeicao not in self._combinacoes:
            self._combinacoes[refeicao] = self.montador.combinacoes(refeicao, metas)
        ops, resumo = self.avaliador.tres_opcoes(self._combinacoes[refeicao], refeicao, metas, politica)
        self.mostradas[refeicao] = ops
        return {"refeicao": NOMES_REFEICAO[refeicao], "metas": metas, "avaliacao": resumo,
                "opcoes": [self._formatar(r, metas) for _, r in ops.iterrows()]}

    def dia(self, politica: str = "bandit") -> dict:
        return {"fonte_metas": self.metas.get("fonte"), "energia_dia_kcal": self.metas["dia"]["energia_kcal"],
                "avisos": self.metas.get("avisos", []),
                "refeicoes": {r: self.opcoes(r, politica) for r in self.refeicoes}}

    def escolher(self, refeicao: str, posicao: int):
        """posicao: 0, 1 ou 2 (opção escolhida entre as últimas mostradas para essa refeição)."""
        if refeicao not in self.mostradas:
            raise ValueError(f"nenhuma opção mostrada ainda para {refeicao}")
        mostradas = self.mostradas[refeicao]
        self.avaliador.registrar_escolha(refeicao, mostradas, posicao)
        if self.usuario_id is not None:                   # guarda a escolha e o que o bandit aprendeu
            codigos = list(mostradas.iloc[posicao].codigos_ordem)
            self.usuarios.registrar_escolha(self.usuario_id, refeicao, posicao, codigos)
            self.usuarios.salvar_estado_bandit(self.usuario_id, self.avaliador.estado())

    # ---------------------------------------------------------------- troca de alimento pelo mapa SOM
    @property
    def som(self):
        if self._som is None:                       # carrega o mapa só na primeira troca pedida
            from .substituidor import Substituidor
            self._som = Substituidor()
            self._tabela = self._som.d.set_index("codigo")
        return self._som

    @staticmethod
    def _mesmo_alimento(nome):
        """Chave do alimento sem corte nem preparo: 'Repolho, cru' e 'Repolho, branco, cozido' -> 'repolho'.
        Quando o primeiro termo da TBCA é genérico ('Carne, frango, peito'), usa os dois primeiros
        ('carne, frango'), para frango e boi continuarem diferentes."""
        termos = [t.strip() for t in sem_acento(nome).split(",")]
        return ", ".join(termos[:2]) if termos[0] in GENERICOS else termos[0]

    def _comuns(self, refeicao, grupo):
        """Códigos dos alimentos que as pessoas comem naquela refeição e grupo, em qualquer região (POF)."""
        if not hasattr(self, "_despensa_toda"):
            self._despensa_toda = pd.read_csv(ARQ_DESPENSA, usecols=["refeicao", "grupo", "codigo"])
        d = self._despensa_toda
        return set(d[(d.refeicao == refeicao) & (d.grupo == grupo)].codigo)

    def substitutos(self, refeicao: str, posicao: int, grupo: str, n: int = 5) -> dict:
        """Alimentos com perfil nutricional parecido com o item `grupo` da opção `posicao`, pelo mapa SOM.

        Regras, nesta ordem:
          * restrições e "não gosta" da pessoa (o Substituidor já filtra);
          * só o que pode ser item do prato (sem molho, pasta, farinha crua; cru só em salada e fruta);
          * um por alimento: cortes e preparos do mesmo alimento contam como um só, e o próprio sai;
          * primeiro os alimentos que as pessoas comem nessa refeição (POF, qualquer região), na ordem do
            mapa; se faltar, completa com os outros. 'comum' diz de qual dos dois veio."""
        item = next(i for i in self.mostradas[refeicao].iloc[posicao].itens if i["grupo"] == grupo)
        res = self.som.substituir(item["alimento"], n=15 * n, restricoes=self.avaliador.restricoes,
                                  evitar=self.avaliador.nao_gosta, codigo=item["codigo"])
        comuns = self._comuns(refeicao, grupo)
        vistos, candidatos = {self._mesmo_alimento(item["alimento"])}, []
        for x in res.get("substitutos", []):
            chave = self._mesmo_alimento(x["nome"])
            if chave in vistos or not serve_no_prato(x["nome"]):
                continue
            if grupo not in ("legumes", "fruta") and re.search(r"\bcrua?\b|\bcrus\b", sem_acento(x["nome"])):
                continue
            vistos.add(chave)
            candidatos.append({**{k: x[k] for k in ("codigo", "nome", "motivo", "distancia_no_mapa", "por_100g")},
                               "comum": x["codigo"] in comuns})
        ordem = [c for c in candidatos if c["comum"]] + [c for c in candidatos if not c["comum"]]
        saida, barrados = [], 0
        for c in ordem:                     # só oferece o que passa na trava depois da troca (ex.: sódio)
            linha = self._linha_trocada(refeicao, posicao, grupo, c["codigo"])
            if linha.motivo_veto.iloc[0]:
                barrados += 1
                continue
            c["gramas"] = next(i["gramas"] for i in linha.itens.iloc[0] if i["grupo"] == grupo)
            c["bem_estar_depois"] = float(linha.bem_estar.iloc[0])
            saida.append(c)
            if len(saida) == n:
                break
        return {"original": item, "gaveta_no_mapa": res.get("gaveta_no_mapa"), "substitutos": saida,
                "barrados_pela_trava": barrados}

    def _linha_trocada(self, refeicao, posicao, grupo, codigo_novo):
        """A opção com o item trocado, já avaliada (trava, nutrientes, bem-estar), sem mudar nada ainda.
        O novo alimento fica com a MESMA energia do item antigo (gramas entre 0,5 e 1,75 vez as do
        original, de 5 em 5)."""
        tab = self._tabela
        metas = self.metas["refeicoes"][refeicao]
        antiga = self.mostradas[refeicao].iloc[posicao]
        itens = [dict(i) for i in antiga.itens]
        k = next(j for j, i in enumerate(itens) if i["grupo"] == grupo)
        velho, novo = itens[k], tab.loc[codigo_novo]
        kcal_item = float(tab.loc[velho["codigo"], "energia_kcal"]) * velho["gramas"] / 100
        gramas = kcal_item / max(float(novo.energia_kcal), 1) * 100
        gramas = float(np.clip(gramas, 0.5 * velho["gramas"], 1.75 * velho["gramas"]))
        gramas = max(round(gramas / 5) * 5, 5)
        itens[k] = {"grupo": grupo, "codigo": codigo_novo, "alimento": novo.descricao, "gramas": float(gramas),
                    "porcao_tipica_g": float(gramas), "subtipo": subtipo(grupo, novo.descricao),
                    "id_base": "" if pd.isna(novo.id_base) else str(novo.id_base)}
        linha = self.avaliador.avaliar(self.montador.montar_linha(itens, tab, metas), refeicao, metas)
        linha["nota"] = antiga.nota
        return linha

    def trocar(self, refeicao: str, posicao: int, grupo: str, codigo_novo: str) -> dict:
        """Troca o item `grupo` da opção `posicao` pelo alimento `codigo_novo` e reavalia a opção.
        A opção trocada substitui a antiga entre as mostradas, então escolher() registra a troca e o bandit
        aprende com a opção como ela ficou. Levanta ValueError se a troca não passar na trava."""
        self.som                                            # garante o mapa e a tabela carregados
        linha = self._linha_trocada(refeicao, posicao, grupo, codigo_novo)
        if linha.motivo_veto.iloc[0]:
            raise ValueError(f"essa troca não passa na trava: {linha.motivo_veto.iloc[0]}")
        ops = self.mostradas[refeicao]
        linha.index = [ops.index[posicao]]
        self.mostradas[refeicao] = pd.concat([ops.iloc[:posicao], linha[ops.columns], ops.iloc[posicao + 1:]])
        return self._formatar(self.mostradas[refeicao].iloc[posicao], self.metas["refeicoes"][refeicao])

    @staticmethod
    def _formatar(r, metas):
        pct = lambda v, m: round(100 * v / m) if m else None
        return {
            "itens": [{"grupo": ROTULO_GRUPO[i["grupo"]], "alimento": i["alimento"], "gramas": i["gramas"],
                       "porcao_tipica_g": i["porcao_tipica_g"], "id_base": i["id_base"]} for i in r.itens],
            "totais": {"energia_kcal": r.energia_kcal, "proteina_g": r.proteina_g,
                       "carboidrato_g": r.carboidrato_total_g, "gordura_g": r.lipidios_g,
                       "fibra_g": r.fibra_g, "sodio_mg": r.sodio_mg},
            "percentual_da_meta": {"energia": pct(r.energia_kcal, metas["energia_kcal"]),
                                   "proteina": pct(r.proteina_g, metas["proteina_g"]),
                                   "fibra": pct(r.fibra_g, metas["fibra_g"]),
                                   "sodio_do_limite": pct(r.sodio_mg, metas["sodio_mg_max"])},
            "bem_estar": float(r.bem_estar), "nota": float(r.nota),
        }

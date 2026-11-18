"""
Cronograma do dia por ingredientes: junta calculadora DRI (via API ou Mockoon), Montador e Avaliador.

    from agents.cronograma import Cronograma
    c = Cronograma({"sexo": "F", "idade": 30, "altura_cm": 163, "peso_kg": 62, "atividade": "pouco_ativo"},
                   restricoes=["sem_lactose"], regiao="Nordeste")
    dia = c.dia()                       # metas + 3 opções para cada refeição
    c.escolher("almoco", 1)             # a pessoa escolheu a 2ª opção do almoço: o bandit aprende

Fluxo de cada refeição:
    calculadora DRI (metas da refeição) -> Montador (todas as combinações, gramas ajustadas às metas)
    -> Avaliador (trava, bem-estar, bandit) -> 3 opções
"""
from __future__ import annotations

from .avaliador_ingredientes import AvaliadorIngredientes
from .cliente_dri import obter_metas
from .montador_ingredientes import GRUPOS_REFEICAO, NOMES_REFEICAO, MontadorIngredientes

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
        self.avaliador.registrar_escolha(refeicao, self.mostradas[refeicao], posicao)

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

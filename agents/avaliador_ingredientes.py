"""
Avaliador por ingredientes: veta, dá nota e escolhe as 3 opções de cada refeição, aprendendo com a escolha.

Recebe do Montador (agents/montador_ingredientes.py) todas as combinações da refeição, já com gramas que
batem as metas da DRI, e faz três coisas:

  1. TRAVA       veta combinações com alérgeno ou restrição da pessoa (mesmas regras do Substituidor),
                 com alimento de que ela não gosta, ou com sódio acima de 1,25 × o limite da refeição.
  2. BEM-ESTAR   nota de 0 a 1 em relação às metas da refeição:
                   20% energia perto da meta, 20% proteína atingida, 20% fibra atingida,
                   15% sódio dentro do limite, 10% gordura dentro da faixa da DRI (até 35% da energia),
                   15% qualidade dos itens (Nutri-Score, menos 0,25 por item ultraprocessado (NOVA 4) e
                   menos 0,2 por item frito, que o Guia Alimentar recomenda evitar).
                 Só a metade de cima das aprovadas segue.
  3. BANDIT      LinUCB escolhe as 3 opções que a pessoa vê e aprende com a escolha:
                   nota = θᵀx + α·√(xᵀA⁻¹x) + λ·bem-estar,   θ = A⁻¹b
                   escolhida: recompensa 1; as outras duas: 0;   A ← A + xxᵀ,  b ← b + r·x
                 x são os subtipos de cada grupo (aves, peixe, leguminosa; arroz, raiz; folha crua; banana...),
                 se tem fritura, a energia relativa à meta, o bem-estar e um viés. O método (LinUCB, a
                 dedução de θ, a incerteza, a simulação) está explicado em docs/avaliador_bandit_explicado.pdf.
                 As 3 opções são variadas: pelo menos 2 alimentos diferentes entre si e, se der, proteínas
                 de tipos diferentes e carboidratos diferentes.

O estado do bandit (A e b de cada refeição) sai em estado() e volta em carregar(), para salvar por usuário.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

from .montador_ingredientes import GRUPOS_REFEICAO, SUBTIPOS, sem_acento
from .substituidor import RESTRICAO

PESOS_BEM_ESTAR = {"energia": 0.20, "proteina": 0.20, "fibra": 0.20, "sodio": 0.15, "gordura": 0.10, "qualidade": 0.15}
NUTRISCORE = {"A": 1.0, "B": 0.75, "C": 0.5, "D": 0.25, "E": 0.0}
SODIO_VETO = 1.25           # × o limite de sódio da refeição
DESCONTO_FRITURA = 0.2      # por item frito, na nota de qualidade


class AvaliadorIngredientes:
    def __init__(self, restricoes=(), nao_gosta=(), alpha: float = 0.8, lam: float = 1.0, seed: int = 0):
        self.restricoes = list(restricoes)
        self.nao_gosta = [sem_acento(x).replace("_", " ") for x in nao_gosta if x]
        self.alpha, self.lam = alpha, lam
        self.rng = np.random.default_rng(seed)
        self.modelos: dict[str, tuple[np.ndarray, np.ndarray]] = {}

    # ---------------------------------------------------------------- 1. trava
    def _veto_item(self, item) -> str | None:
        """Motivo para vetar UM alimento (restrição ou não gosta), ou None."""
        nome = sem_acento(item["descricao"])
        for r in self.restricoes:
            col, valor, rx = RESTRICAO.get(r, (None, None, None))
            if col and col in item.index and int(item[col]) != valor:
                return f"restrição: {r}"
            if rx and re.search(rx, nome):
                return f"restrição: {r}"
        id_base = sem_acento(item.get("id_base", "") or "").replace("_", " ")
        for x in self.nao_gosta:
            if x in nome or x in id_base.split("|"):
                return f"não gosta: {x}"
        return None

    def _vetos(self, df, meta_sodio):
        itens = df.attrs.get("itens")
        por_item = {c: self._veto_item(r) for c, r in itens.iterrows()} if itens is not None else {}
        motivos = []
        for cods, sodio in zip(df.codigos_ordem, df.sodio_mg):
            m = next((por_item[c] for c in cods if por_item.get(c)), None)
            if m is None and sodio > SODIO_VETO * meta_sodio:
                m = f"sódio acima de {SODIO_VETO:g} × o limite da refeição ({meta_sodio:.0f} mg)"
            motivos.append(m)
        return motivos

    # ---------------------------------------------------------------- 2. bem-estar
    @staticmethod
    def _qualidade(nutriscores, novas, itens):
        notas = [NUTRISCORE.get(str(ns), 0.5) - 0.25 * (int(nv) == 4) for ns, nv in zip(nutriscores, novas)]
        fritos = sum("frit" in sem_acento(i["alimento"]) for i in itens)
        return float(np.clip(np.mean(notas) - DESCONTO_FRITURA * fritos, 0, 1))

    def bem_estar(self, df, metas):
        energia = 1 - np.minimum(np.abs(df.energia_kcal / metas["energia_kcal"] - 1), 1)
        prot = np.minimum(df.proteina_g / max(metas["proteina_g"], 1e-6), 1)
        fibra = np.minimum(df.fibra_g / max(metas["fibra_g"], 1e-6), 1)
        lim = metas["sodio_mg_max"]
        sodio = np.where(df.sodio_mg <= lim, 1, np.maximum(0, 1 - (df.sodio_mg - lim) / lim))
        gmax = metas.get("gordura_g_max", 0.35 * metas["energia_kcal"] / 9)
        gordura = np.where(df.lipidios_g <= gmax, 1, np.maximum(0, 1 - (df.lipidios_g - gmax) / gmax))
        qual = np.array([self._qualidade(ns, nv, it) for ns, nv, it in zip(df.nutriscore, df.nova, df.itens)])
        w = PESOS_BEM_ESTAR
        return (w["energia"] * energia + w["proteina"] * prot + w["fibra"] * fibra + w["sodio"] * sodio
                + w["gordura"] * gordura + w["qualidade"] * qual).round(4)

    # ---------------------------------------------------------------- características (o que o bandit vê)
    @staticmethod
    def nomes_caracteristicas(refeicao):
        nomes = []
        for g in GRUPOS_REFEICAO[refeicao]:
            nomes += [f"{g}:{s}" for s, _ in SUBTIPOS[g]] + [f"{g}:outro"]
        return nomes + ["frito", "energia/meta", "bem_estar", "viés"]

    def _caracteristicas(self, df, refeicao, metas):
        nomes = self.nomes_caracteristicas(refeicao)
        pos = {n: k for k, n in enumerate(nomes)}
        X = np.zeros((len(df), len(nomes)))
        for i, itens in enumerate(df.itens):
            for it in itens:
                X[i, pos[f"{it['grupo']}:{it['subtipo']}"]] = 1
            X[i, pos["frito"]] = float(any("frit" in sem_acento(it["alimento"]) for it in itens))
        X[:, pos["energia/meta"]] = df.energia_kcal / metas["energia_kcal"]
        X[:, pos["bem_estar"]] = df.bem_estar
        X[:, pos["viés"]] = 1
        return X

    # ---------------------------------------------------------------- 3. bandit
    def _modelo(self, refeicao):
        if refeicao not in self.modelos:
            d = len(self.nomes_caracteristicas(refeicao))
            self.modelos[refeicao] = (np.eye(d), np.zeros(d))
        return self.modelos[refeicao]

    def avaliar(self, combinacoes: pd.DataFrame, refeicao: str, metas: dict) -> pd.DataFrame:
        """Acrescenta motivo_veto, bem_estar e o vetor x a cada combinação."""
        df = combinacoes.copy()
        df.attrs = combinacoes.attrs
        df["motivo_veto"] = self._vetos(df, metas["sodio_mg_max"])
        df["bem_estar"] = self.bem_estar(df, metas)
        df["x"] = list(self._caracteristicas(df, refeicao, metas))
        return df

    def tres_opcoes(self, combinacoes: pd.DataFrame, refeicao: str, metas: dict, politica: str = "bandit"):
        """Devolve (as 3 opções, resumo da avaliação). politica: bandit, fixa (só bem-estar) ou aleatoria."""
        df = self.avaliar(combinacoes, refeicao, metas)
        aprovadas = df[df.motivo_veto.isna()]
        resumo = {"combinacoes": len(df), "vetadas": int(df.motivo_veto.notna().sum()),
                  "motivos_veto": df.motivo_veto.value_counts().head(5).to_dict()}
        if aprovadas.empty:
            resumo["saudaveis"] = 0
            return aprovadas, resumo
        ok = aprovadas[aprovadas.bem_estar >= aprovadas.bem_estar.median()]
        resumo["saudaveis"] = len(ok)
        X = np.stack(ok.x.to_numpy())
        if politica == "bandit":
            A, b = self._modelo(refeicao)
            Ainv = np.linalg.inv(A)
            nota = X @ (Ainv @ b) + self.alpha * np.sqrt(np.einsum("ij,ij->i", X @ Ainv, X)) \
                + self.lam * ok.bem_estar.to_numpy()
        elif politica == "fixa":
            nota = ok.bem_estar.to_numpy()
        else:
            nota = self.rng.random(len(ok))
        ordem = np.argsort(-nota)
        cods = ok.codigos.to_numpy()
        tipo = lambda g: [next((i["subtipo"] for i in it if i["grupo"] == g), "") for it in ok.itens]
        item = lambda g: [next((i["codigo"] for i in it if i["grupo"] == g), "") for it in ok.itens]
        prot, carb = tipo("proteina"), item("carboidrato")
        escolhidas: list[int] = []
        # variedade, do mais exigente ao menos: alimentos diferentes, proteína de outro tipo, outro carboidrato
        for minimo, prot_dif, carb_dif in ((2, True, True), (2, True, False), (2, False, False), (1, False, False),
                                           (0, False, False)):
            for i in ordem:
                if len(escolhidas) == 3:
                    break
                if i in escolhidas:
                    continue
                if all(len(cods[i] - cods[j]) >= minimo and (not prot_dif or prot[i] != prot[j])
                       and (not carb_dif or carb[i] != carb[j]) for j in escolhidas):
                    escolhidas.append(i)
        opcoes = ok.iloc[escolhidas].copy()
        opcoes["nota"] = nota[escolhidas].round(3)
        return opcoes, resumo

    def registrar_escolha(self, refeicao: str, mostradas: pd.DataFrame, posicao_escolhida: int):
        """posicao_escolhida: 0, 1 ou 2 (a ordem em que as opções foram mostradas)."""
        A, b = self._modelo(refeicao)
        for k, x in enumerate(mostradas.x):
            A += np.outer(x, x)
            b += (1.0 if k == posicao_escolhida else 0.0) * x
        self.modelos[refeicao] = (A, b)

    def explicar(self, refeicao: str, top: int = 5):
        """O que o bandit aprendeu: os maiores e os menores pesos θ."""
        A, b = self._modelo(refeicao)
        th = pd.Series(np.linalg.solve(A, b), index=self.nomes_caracteristicas(refeicao)).drop("viés")
        return th.sort_values(ascending=False).head(top), th.sort_values().head(top)

    # ---------------------------------------------------------------- salvar e carregar por usuário
    def estado(self) -> dict:
        return {r: {"A": A.tolist(), "b": b.tolist()} for r, (A, b) in self.modelos.items()}

    def carregar(self, estado: dict):
        for r, m in (estado or {}).items():
            A, b = np.array(m["A"]), np.array(m["b"])
            if len(b) == len(self.nomes_caracteristicas(r)):        # ignora estado de versão antiga
                self.modelos[r] = (A, b)

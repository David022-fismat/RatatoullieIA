"""
Substituidor: usa o mapa auto-organizável (SOM) treinado na TBCA para trocar um ingrediente por outro de
perfil nutricional parecido ("não tenho frango", "não gosto de abobrinha", "quero variar o arroz").

Dados: kb/som/tbca_som.csv (2.556 alimentos da TBCA tratada, sem as receitas: 37 nutrientes normalizados por Min-Max, grupo
NOVA, Nutri-Score, alérgenos, dietas e a ligação com os ingredientes do app) e kb/som/som_tbca.npz (o mapa).
Para refazer: python scripts/atualizar_som.py (limpa as receitas, liga os ingredientes, monta a tabela e treina).

Como acha os substitutos:
  1. cada alimento está numa "gaveta" (neurônio) do mapa 10x10;
  2. os candidatos são ordenados pela distância entre as gavetas no mapa (0 = mesma gaveta, 1 = vizinha...)
     e, empatou, pela distância entre os 37 nutrientes;
  3. ficam só os do mesmo grupo do prato (proteína com proteína ou leguminosa, base com base), os que
     respeitam as restrições do perfil (alérgenos e dietas da TBCA) e os que não são o próprio alimento.
Com metodo="knn" ordena só pela distância (sem o mapa), para comparar.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
ARQ_TABELA = RAIZ / "kb" / "som" / "tbca_som.csv"
ARQ_MAPA = RAIZ / "kb" / "som" / "som_tbca.npz"

# restrição do perfil -> coluna da TBCA que precisa ser 1 (dieta) ou 0 (alérgeno), e um reforço pelo nome
RESTRICAO = {
    "vegetariano": ("dieta_vegetariano", 1, None),
    "sem_lactose": ("alergeno_leite", 0, r"\bleite|queijo|manteiga|iogurte|requeijao|creme de leite"),
    "alergia_ovo": ("alergeno_ovos", 0, r"\bovo|maionese|omelete"),
    "celiaco": ("alergeno_gluten", 0, r"trigo|\bpao\b|macarrao|biscoito|aveia|cevada|centeio"),
    "sem_carne_vermelha": (None, None, r"\bboi\b|bovin|porco|suin|carneiro|cordeiro|cabrito|linguica|bacon|"
                                       r"mortadela|presunto|salame|figado|charque|carne seca|toucinho"),
}
# grupos que podem trocar entre si no prato (a fonte de proteína pode ser animal ou leguminosa)
TROCA_ENTRE_GRUPOS = {"proteína animal": {"proteína animal", "leguminosa"},
                      "leguminosa": {"leguminosa", "proteína animal"}}


def _norm(t):
    t = unicodedata.normalize("NFKD", str(t).lower())
    return "".join(c for c in t if not unicodedata.combining(c))


class Substituidor:
    def __init__(self, arq_tabela=ARQ_TABELA, arq_mapa=ARQ_MAPA):
        if not Path(arq_mapa).exists():
            raise FileNotFoundError(f"{arq_mapa} não existe: rode python scripts/treinar_som.py")
        self.d = pd.read_csv(arq_tabela, dtype={"nutriscore": str}).fillna({"id_base": "", "nutriscore": ""})
        m = np.load(arq_mapa)
        self.pesos, self.lado = m["pesos"], int(m["lado"])
        self.qe, self.te = float(m["qe"]), float(m["te"])
        self.X = self.d[[str(c) for c in m["colunas"]]].to_numpy(float)       # 37 nutrientes, Min-Max
        W = self.pesos.reshape(-1, self.X.shape[1])
        d2 = (self.X ** 2).sum(1)[:, None] + (W ** 2).sum(1)[None, :] - 2 * self.X @ W.T
        bmu = d2.argmin(1)
        self.gaveta = np.column_stack([bmu // self.lado, bmu % self.lado])    # (linha, coluna) no mapa
        self.nomes_norm = [_norm(n) for n in self.d.descricao]
        self.base = [set(filter(None, str(i).split("|"))) for i in self.d.id_base]

    # ------------------------------------------------------------------ achar o alimento pedido
    def achar(self, texto, id_app=None):
        """Índice do alimento na TBCA: primeiro pelo id da base do app, depois pelas palavras do nome."""
        if id_app:
            cand = [i for i, ids in enumerate(self.base) if id_app in ids]
            if cand:
                return min(cand, key=lambda i: len(self.nomes_norm[i]))          # o de nome mais simples
        palavras = _norm(texto).replace(",", " ").split()
        if not palavras:
            return None
        cand = [i for i, n in enumerate(self.nomes_norm) if all(p in n for p in palavras)]
        if not cand:
            return None
        # prefere: começa com a 1ª palavra; não é prato pronto; está ligado ao app; nome mais curto
        return min(cand, key=lambda i: (not self.nomes_norm[i].startswith(palavras[0]), "(" in self.nomes_norm[i],
                                        not self.base[i], len(self.nomes_norm[i])))

    def _permitido(self, j, restricoes):
        for r in restricoes:
            col, valor, rx = RESTRICAO.get(r, (None, None, None))
            if col and int(self.d.at[j, col]) != valor:
                return False
            if rx and re.search(rx, self.nomes_norm[j]):
                return False
        return True

    # ------------------------------------------------------------------ substituir
    def substituir(self, texto, n=5, mesmo_grupo=True, restricoes=(), evitar=(), id_app=None, metodo="som",
                   so_na_base=False):
        """so_na_base=True: só alimentos ligados a um ingrediente da base do app (dá para trocar na receita)."""
        i = self.achar(texto, id_app)
        if i is None:
            return {"erro": f"não achei '{texto}' na TBCA", "dica": "tente o nome do alimento (ex.: frango, arroz)"}
        dist = np.sqrt(((self.X - self.X[i]) ** 2).sum(1))
        grade = np.abs(self.gaveta - self.gaveta[i]).max(1)              # quantas casas de distância no mapa
        ordem = np.argsort(dist) if metodo == "knn" else np.lexsort((dist, grade))
        evitar = [_norm(e) for e in evitar]
        primeiro = self.nomes_norm[i].split(",")[0]                       # "carne", "arroz"...
        grupo = self.d.grupo[i]
        aceitos = TROCA_ENTRE_GRUPOS.get(grupo, {grupo})

        saida = []
        for j in ordem:
            if j == i or (self.base[i] and self.base[j] & self.base[i]):  # o próprio ingrediente em outro preparo
                continue
            if not self.base[i] and self.nomes_norm[j].split(",")[0] == primeiro:
                continue
            if mesmo_grupo and self.d.grupo[j] not in aceitos:
                continue
            if self.d.grupo[j] != grupo and re.search(r"extrato|fluido|bebida|pacoca|doce", self.nomes_norm[j]):
                continue                                                  # leguminosa no lugar de carne: só comida
            if not self._permitido(j, restricoes) or any(e and e in self.nomes_norm[j] for e in evitar):
                continue
            if so_na_base and not self.base[j]:
                continue
            saida.append(self._item(j, grade[j], dist[j]))
            if len(saida) == n:
                break
        return {"alimento": self.d.descricao[i], "grupo": grupo, "gaveta_no_mapa": [int(v) for v in self.gaveta[i]],
                "por_100g": self._nutrientes(i),
                "metodo": "SOM (mapa auto-organizável) 10x10 da TBCA" if metodo != "knn" else "kNN (só distância)",
                "substitutos": saida}

    def _nutrientes(self, j):
        r = self.d.iloc[j]
        return {"kcal": round(float(r.energia_kcal)), "proteina_g": round(float(r.proteina_g), 1),
                "carboidrato_g": round(float(r.carboidrato_total_g), 1), "lipidios_g": round(float(r.lipidios_g), 1),
                "fibra_g": round(float(r.fibra_g), 1), "nova": int(r.nova), "nutriscore": r.nutriscore}

    def _item(self, j, casas, dist):
        motivo = ("mesma gaveta do mapa" if casas == 0 else
                  f"gaveta a {casas} casa{'s' if casas > 1 else ''} no mapa")
        return {"nome": self.d.descricao[j], "motivo": f"{motivo} (perfil nutricional parecido)",
                "distancia_no_mapa": int(casas), "distancia_nutricional": round(float(dist), 3),
                "por_100g": self._nutrientes(j), "na_base_do_app": sorted(self.base[j])}

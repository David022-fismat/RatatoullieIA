"""
Treina o mapa auto-organizável (SOM) da TBCA e salva o que o app precisa para usar o mapa.

    pip install minisom openpyxl scikit-learn   (só para treinar; o app usa só numpy e pandas)
    python scripts/treinar_som.py         # lê kb/som/tbca_som.csv, gera kb/som/som_tbca.npz

Entrada do mapa: os 37 nutrientes por 100 g dos ALIMENTOS da TBCA (sem receitas), normalizados por Min-Max
(colunas n_*, entre 0 e 1). Para refazer tudo (limpeza, ligação, tabela e mapa): python scripts/atualizar_som.py
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from agents.substituidor import ARQ_MAPA, ARQ_TABELA   # noqa: E402

LADO = 10              # 10x10: no teste kNN x SOM, mapas maiores pioraram os vizinhos
ITERACOES = 30000
SEMENTE = 0


def main():
    from minisom import MiniSom
    d = pd.read_csv(ARQ_TABELA)
    colunas = [c for c in d.columns if c.startswith("n_")]
    X = d[colunas].to_numpy(float)
    som = MiniSom(LADO, LADO, X.shape[1], sigma=LADO / 2, learning_rate=0.5,
                  neighborhood_function="gaussian", random_seed=SEMENTE)
    som.pca_weights_init(X)
    som.train(X, ITERACOES, random_order=True)
    qe, te = som.quantization_error(X), som.topographic_error(X)
    np.savez(ARQ_MAPA, pesos=som.get_weights(), colunas=np.array(colunas), lado=LADO, iteracoes=ITERACOES,
             semente=SEMENTE, qe=qe, te=te)
    print(f"SOM {LADO}x{LADO} treinado com {len(d)} alimentos da TBCA ({len(colunas)} nutrientes) | "
          f"erro de quantização {qe:.3f} | erro topográfico {te:.3f}")
    print(f"salvo em {ARQ_MAPA.relative_to(RAIZ)}")


if __name__ == "__main__":
    main()

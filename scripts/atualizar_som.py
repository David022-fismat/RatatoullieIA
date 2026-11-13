"""
Refaz a base do mapa SOM e retreina o mapa, na ordem certa:

    pip install minisom openpyxl scikit-learn     (só para refazer; o app usa só numpy e pandas)
    python scripts/atualizar_som.py

  1. limpar_receitas_tbca.py    -> kb/som/tbca_receitas_removidas.csv  (receitas que saíram e o motivo)
  2. ligar_ingredientes_tbca.py -> kb/som/ingrediente_tbca.csv         (ingrediente do app -> alimento da TBCA)
  3. preparar_tbca_som.py       -> kb/som/tbca_som.csv, kb/som/parametros_minmax.csv
  4. treinar_som.py             -> kb/som/som_tbca.npz                 (o mapa 10x10)
"""
import runpy
import sys
from pathlib import Path

PASTA = Path(__file__).resolve().parent
sys.path.insert(0, str(PASTA))

for etapa in ["limpar_receitas_tbca", "ligar_ingredientes_tbca", "preparar_tbca_som", "treinar_som"]:
    print(f"\n=== {etapa}.py ===")
    runpy.run_path(str(PASTA / f"{etapa}.py"), run_name="__main__")

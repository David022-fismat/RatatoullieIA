"""
Ponto de entrada do app (o Streamlit Cloud procura este arquivo). A interface fica em layout/app.py.

    streamlit run app.py
"""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parent / "layout" / "app.py"), run_name="__main__")

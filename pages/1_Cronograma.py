"""Página "Cronograma" no menu lateral do app (streamlit run app.py). A interface fica em layout/cronograma_app.py."""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parent.parent / "layout" / "cronograma_app.py"), run_name="__main__")

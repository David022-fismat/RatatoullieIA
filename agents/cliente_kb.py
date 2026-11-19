"""
Cliente da API da base de conhecimento (TBCA sem receitas + despensa da POF).

Aponta para KB_API_URL (padrão http://localhost:3002), onde roda o mock do Mockoon:
    npx @mockoon/cli start --data mocks/tbca.json
Se a API não responder, lê os mesmos dados dos arquivos do repositório (kb/som/tbca_som.csv e
kb/cronograma/despensa.csv) e aplica os mesmos filtros. O DataFrame devolvido diz de onde veio em .attrs["fonte"].

Filtros: os mesmos do Mockoon, como argumentos nomeados:
    buscar_alimentos("frango", grupo_eq="proteína animal", proteina_g_gte=20, limite=10)
    sufixos: _eq, _ne, _gt, _gte, _lt, _lte, _like (regex, sem diferenciar maiúsculas), _start, _end
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

RAIZ = Path(__file__).resolve().parent.parent
ARQ_ALIMENTOS = RAIZ / "kb" / "som" / "tbca_som.csv"
ARQ_DESPENSA = RAIZ / "kb" / "cronograma" / "despensa.csv"
TIPOS = {"nutriscore": str, "id_base": str}


def _url():
    return os.getenv("KB_API_URL", "http://localhost:3002").rstrip("/")


def _get(caminho, params):
    q = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    with urllib.request.urlopen(f"{_url()}/{caminho}{'?' + q if q else ''}",
                                timeout=float(os.getenv("KB_TIMEOUT", "5"))) as r:
        return json.loads(r.read().decode())


def _filtrar_local(df, filtros):
    """Os filtros do Mockoon aplicados a um DataFrame (para o plano B sem API)."""
    for chave, valor in filtros.items():
        m = re.match(r"^(.*)_(eq|ne|gt|gte|lt|lte|like|start|end)$", chave)
        if not m or m.group(1) not in df.columns:
            continue
        col, op = df[m.group(1)], m.group(2)
        num = pd.to_numeric(col, errors="coerce")
        try:
            v = float(valor)
        except (TypeError, ValueError):
            v = None
        if op in ("eq", "ne"):
            igual = (col.astype(str) == str(valor)) | ((num == v) if v is not None else False)
            df = df[igual if op == "eq" else ~igual]
        elif op in ("gt", "gte", "lt", "lte") and v is not None:
            df = df[{"gt": num > v, "gte": num >= v, "lt": num < v, "lte": num <= v}[op]]
        elif op in ("like", "start", "end"):
            padrao = {"like": str(valor), "start": f"^{valor}", "end": f"{valor}$"}[op]
            df = df[col.astype(str).str.contains(padrao, case=False, regex=True, na=False)]
    return df


def _local(arquivo, texto=None, limite=None, **filtros):
    df = pd.read_csv(arquivo, dtype=TIPOS).fillna({"nutriscore": "", "id_base": ""})
    if arquivo == ARQ_DESPENSA:
        df.insert(0, "id", df.regiao + "|" + df.refeicao + "|" + df.grupo + "|" + df.codigo)
    if texto:
        df = df[df.astype(str).apply(lambda c: c.str.contains(texto, case=False, regex=False)).any(axis=1)]
    df = _filtrar_local(df, filtros)
    return df.head(limite) if limite else df


def _consultar(caminho, arquivo, texto=None, limite=None, **filtros) -> pd.DataFrame:
    params = {"search": texto, "limit": limite, **filtros}
    try:
        df = pd.DataFrame(_get(caminho, params))
        if not df.empty:
            df = df.astype({c: t for c, t in TIPOS.items() if c in df.columns})
        df.attrs["fonte"] = f"API em {_url()}"
        return df
    except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
        df = _local(arquivo, texto, limite, **filtros)
        df.attrs["fonte"] = f"arquivo local (API fora do ar: {type(e).__name__})"
        return df


def buscar_alimentos(texto: str | None = None, limite: int | None = 20, **filtros) -> pd.DataFrame:
    """Alimentos da TBCA sem receitas. texto: busca em todos os campos (como o ?search= do Mockoon)."""
    return _consultar("alimentos", ARQ_ALIMENTOS, texto, limite, **filtros)


def alimento(codigo: str) -> dict | None:
    """Um alimento pelo código da TBCA, ou None se não existir."""
    try:
        return _get(f"alimentos/{urllib.parse.quote(codigo)}", {})
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    except (urllib.error.URLError, TimeoutError, OSError):
        df = _local(ARQ_ALIMENTOS, codigo_eq=codigo)
        return json.loads(df.iloc[0].to_json(force_ascii=False)) if len(df) else None


def despensa(regiao: str | None = None, refeicao: str | None = None, grupo: str | None = None) -> pd.DataFrame:
    """Linhas da despensa (alimentos mais comidos na POF, com a porção típica) para o Montador."""
    filtros = {k + "_eq": v for k, v in (("regiao", regiao), ("refeicao", refeicao), ("grupo", grupo)) if v}
    return _consultar("despensa", ARQ_DESPENSA, None, None, **filtros)

"""
Cliente da API da calculadora DRI. O Montador pede as metas por aqui.

Para onde ele aponta (variável de ambiente DRI_API_URL, padrão http://localhost:3001):
  * o mock do Mockoon:    npx @mockoon/cli start --data mocks/dri.json      (porta 3001)
  * a API de verdade:     python -m servicos.api_dri                         (porta 3001)
  * outro servidor:       export DRI_API_URL=http://endereco:porta

Se a API não responder (fora do ar, erro 5xx, demora mais que DRI_TIMEOUT segundos), o cliente calcula as
metas localmente com agents/calculadora_dri.py e marca "fonte": "cálculo local (API fora do ar)".
Se a API responder 422 (perfil fora do escopo: menor de 19 anos, gestante...), o cliente NÃO calcula por
conta própria: levanta PerfilRecusado com a mensagem da API, para o app encaminhar a pessoa.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from .calculadora_dri import ForaDoEscopo, calcular_dri


class PerfilRecusado(ValueError):
    """A calculadora recusou o perfil (422). A mensagem explica o motivo."""


def _url():
    return os.getenv("DRI_API_URL", "http://localhost:3001").rstrip("/")


def obter_metas(dados: dict, cenario: str | None = None, usar_api: bool = True) -> dict:
    """dados: sexo, idade, altura_cm, peso_kg, atividade (e opcionalmente gestante, amamentando).
    cenario: só para testes com o Mockoon (vai no cabeçalho X-Cenario: 'erro', 'lento').
    usar_api=False: calcula direto, sem HTTP."""
    if usar_api:
        corpo = json.dumps(dados).encode()
        cabecalhos = {"Content-Type": "application/json"}
        if cenario:
            cabecalhos["X-Cenario"] = cenario
        req = urllib.request.Request(f"{_url()}/dri", data=corpo, headers=cabecalhos, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=float(os.getenv("DRI_TIMEOUT", "5"))) as r:
                metas = json.loads(r.read().decode())
                metas.setdefault("fonte", f"API em {_url()}")
                return metas
        except urllib.error.HTTPError as e:
            if e.code == 422:
                try:
                    msg = json.loads(e.read().decode()).get("erro", "perfil recusado")
                except json.JSONDecodeError:
                    msg = "perfil recusado"
                raise PerfilRecusado(msg) from e
            motivo = f"erro {e.code}"
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as e:
            motivo = type(e).__name__
        metas = _local(dados)
        metas["fonte"] = f"cálculo local (API fora do ar: {motivo})"
        return metas
    return _local(dados)


def _local(dados):
    try:
        return calcular_dri(dados["sexo"], float(dados["idade"]), float(dados["altura_cm"]),
                            float(dados["peso_kg"]), dados["atividade"],
                            gestante=bool(dados.get("gestante")), amamentando=bool(dados.get("amamentando")))
    except ForaDoEscopo as e:
        raise PerfilRecusado(str(e)) from e

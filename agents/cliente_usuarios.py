"""
Cliente da API de usuários: cadastra a pessoa (e devolve o ID dela), guarda o perfil e o estado do bandit,
e registra cada escolha do cronograma.

Aponta para USUARIOS_API_URL (padrão http://localhost:3003), onde roda o mock do Mockoon:
    npx @mockoon/cli start --data mocks/usuarios.json
O Mockoon guarda tudo em memória: ao reiniciar, volta só o usuário de exemplo (id "exemplo").

Se a API não responder, o cliente passa a guardar num arquivo local (usuarios_local.json, fora do git),
com o mesmo formato. cliente.fonte diz qual dos dois está em uso.

    from agents.cliente_usuarios import ClienteUsuarios
    cli = ClienteUsuarios()
    u = cli.criar("Ana", {"sexo": "F", "idade": 30, "altura_cm": 163, "peso_kg": 62, "atividade": "ativo"},
                  regiao="Sul", restricoes=["vegetariano"])
    u["id"]                                   # o ID gerado
    cli.registrar_escolha(u["id"], "almoco", 1, ["C0209A", ...])
    cli.salvar_estado_bandit(u["id"], estado)
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
CAMPOS_DRI = ("sexo", "idade", "altura_cm", "peso_kg", "atividade")


class UsuarioNaoEncontrado(KeyError):
    pass


def _agora():
    return datetime.now().astimezone().isoformat(timespec="seconds")


class ClienteUsuarios:
    def __init__(self, url: str | None = None, arquivo_local: str | Path | None = None):
        self.url = (url or os.getenv("USUARIOS_API_URL", "http://localhost:3003")).rstrip("/")
        self.arquivo_local = Path(arquivo_local or RAIZ / "usuarios_local.json")
        self.local = False
        self.fonte = f"API em {self.url}"

    # ---------------------------------------------------------------- transporte (API ou arquivo)
    def _http(self, metodo, caminho, corpo=None):
        dados = json.dumps(corpo).encode() if corpo is not None else None
        req = urllib.request.Request(f"{self.url}/{caminho}", data=dados, method=metodo,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=float(os.getenv("USUARIOS_TIMEOUT", "5"))) as r:
            return json.loads(r.read().decode() or "null")

    def _chamar(self, metodo, caminho, corpo=None):
        if not self.local:
            try:
                return self._http(metodo, caminho, corpo)
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    raise UsuarioNaoEncontrado(caminho) from e
                raise
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                self.local = True
                self.fonte = f"arquivo local {self.arquivo_local.name} (API fora do ar: {type(e).__name__})"
        return self._arquivo(metodo, caminho, corpo)

    def _ler(self):
        if self.arquivo_local.exists():
            return json.loads(self.arquivo_local.read_text(encoding="utf-8"))
        return {"usuarios": [], "escolhas": []}

    def _arquivo(self, metodo, caminho, corpo):
        """O mesmo CRUD do Mockoon, num arquivo JSON."""
        db = self._ler()
        caminho, _, consulta = caminho.partition("?")
        recurso, _, ident = caminho.partition("/")
        itens = db[recurso]
        if metodo == "GET" and not ident:
            filtros = dict(p.split("=", 1) for p in consulta.split("&") if p)
            return [i for i in itens if all(str(i.get(k[:-3] if k.endswith("_eq") else k)) == v
                                            for k, v in filtros.items())]
        if metodo == "POST":
            novo = dict(corpo)
            if "id" not in novo:
                nums = [i["id"] for i in itens if isinstance(i.get("id"), int)]
                novo["id"] = (max(nums) + 1) if nums else (str(uuid.uuid4()) if recurso == "usuarios" else 1)
            itens.append(novo)
            self.arquivo_local.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
            return novo
        pos = next((k for k, i in enumerate(itens) if str(i.get("id")) == ident), None)
        if pos is None:
            raise UsuarioNaoEncontrado(caminho)
        if metodo == "PATCH":
            itens[pos].update(corpo)
            self.arquivo_local.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")
        return itens[pos]

    # ---------------------------------------------------------------- usuários
    def criar(self, nome: str, dados_dri: dict, regiao: str = "Brasil", restricoes=(), nao_gosta=()) -> dict:
        faltando = [c for c in CAMPOS_DRI if c not in dados_dri]
        if faltando:
            raise ValueError(f"dados_dri sem: {', '.join(faltando)}")
        corpo = {"nome": nome, "criado_em": _agora(), "dados_dri": dados_dri, "regiao": regiao,
                 "restricoes": list(restricoes), "nao_gosta": list(nao_gosta), "estado_bandit": {}}
        return self._chamar("POST", "usuarios", corpo)

    def obter(self, usuario_id: str) -> dict:
        return self._chamar("GET", f"usuarios/{usuario_id}")

    def atualizar(self, usuario_id: str, **campos) -> dict:
        return self._chamar("PATCH", f"usuarios/{usuario_id}", campos)

    def salvar_estado_bandit(self, usuario_id: str, estado: dict) -> dict:
        return self.atualizar(usuario_id, estado_bandit=estado)

    # ---------------------------------------------------------------- escolhas
    def registrar_escolha(self, usuario_id: str, refeicao: str, posicao: int, codigos: list[str]) -> dict:
        return self._chamar("POST", "escolhas", {"usuario_id": usuario_id, "data": _agora(), "refeicao": refeicao,
                                                 "posicao": int(posicao), "codigos": list(codigos)})

    def escolhas(self, usuario_id: str, refeicao: str | None = None) -> list[dict]:
        consulta = f"usuario_id_eq={usuario_id}" + (f"&refeicao_eq={refeicao}" if refeicao else "")
        return self._chamar("GET", f"escolhas?{consulta}")

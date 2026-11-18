"""
API da calculadora DRI (a versão de verdade). O Mockoon (mocks/dri.json) imita esta mesma API.

    python -m servicos.api_dri                 # sobe em http://localhost:3001
    python -m servicos.api_dri --porta 8001

Rotas:
    GET  /saude   -> {"status": "ok"}
    POST /dri     corpo: {"sexo": "F", "idade": 30, "altura_cm": 165, "peso_kg": 62,
                          "atividade": "pouco_ativo", "gestante": false, "amamentando": false}
                  200: metas do dia e por refeição (ver agents/calculadora_dri.py)
                  422: perfil fora do escopo ou inválido -> {"erro": "...", "tipo": "fora_do_escopo" | "invalido"}

Só usa a biblioteca padrão do Python (sem dependências novas).
"""
from __future__ import annotations

import argparse
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agents.calculadora_dri import ForaDoEscopo, calcular_dri   # noqa: E402

CAMPOS = ("sexo", "idade", "altura_cm", "peso_kg", "atividade")


class Handler(BaseHTTPRequestHandler):
    def _responder(self, status, corpo):
        dados = json.dumps(corpo, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def do_GET(self):
        if self.path.rstrip("/") == "/saude":
            return self._responder(200, {"status": "ok"})
        self._responder(404, {"erro": "rota não encontrada"})

    def do_POST(self):
        if self.path.rstrip("/") != "/dri":
            return self._responder(404, {"erro": "rota não encontrada"})
        try:
            corpo = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            faltando = [c for c in CAMPOS if c not in corpo]
            if faltando:
                raise ValueError(f"faltam campos: {', '.join(faltando)}")
            metas = calcular_dri(corpo["sexo"], float(corpo["idade"]), float(corpo["altura_cm"]),
                                 float(corpo["peso_kg"]), corpo["atividade"],
                                 gestante=bool(corpo.get("gestante")), amamentando=bool(corpo.get("amamentando")))
        except ForaDoEscopo as e:
            return self._responder(422, {"erro": str(e), "tipo": "fora_do_escopo"})
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            return self._responder(422, {"erro": str(e), "tipo": "invalido"})
        self._responder(200, metas)

    def log_message(self, fmt, *args):          # log curto no terminal
        sys.stderr.write(f"[api_dri] {self.command} {self.path} {args[1] if len(args) > 1 else ''}\n")


def main():
    p = argparse.ArgumentParser(description="API da calculadora DRI")
    p.add_argument("--porta", type=int, default=3001)
    args = p.parse_args()
    servidor = ThreadingHTTPServer(("0.0.0.0", args.porta), Handler)
    print(f"API DRI em http://localhost:{args.porta}  (POST /dri, GET /saude) — Ctrl+C para parar")
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

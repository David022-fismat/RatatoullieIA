"""
Agente Montador: PROPÕE receitas candidatas. Não decide nada; quem decide é o Avaliador.

Dois modos, mesma saída (lista de receitas em JSON):
  - modo "llm"  : pede ao LLM receitas usando só ingredientes da base (entrega desta semana)
  - modo "base" : busca na base de receitas + tabela de substituições (sem LLM; também é o plano B)

Formato de cada receita devolvida (o "contrato" com o Avaliador):
  {"nome": str, "porcoes": int, "tempo_min": int, "preparo": str,
   "ingredientes": [{"id": str, "gramas": float}, ...], "origem": "llm" | "base"}
"""
from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path

KB = Path(__file__).parent / "kb"


def carregar_substituicoes():
    with open(KB / "substituicoes.csv", encoding="utf-8") as f:
        return {r["ingrediente"]: r["substitutos"].split("|") for r in csv.DictReader(f)}


# ----------------------------------------------------------------------------
# Cliente de LLM (troque aqui se o grupo usar outro provedor)
# ----------------------------------------------------------------------------
def llm_anthropic(prompt: str) -> str:
    """Chama a API da Anthropic. Precisa de `pip install anthropic` e ANTHROPIC_API_KEY."""
    import anthropic
    cliente = anthropic.Anthropic()
    resp = cliente.messages.create(
        model=os.getenv("MODELO_LLM", "claude-haiku-5-5"),
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text


class Montador:
    def __init__(self, ingredientes, receitas, guardiao, llm=None, modo=None):
        self.ing, self.rec, self.guardiao = ingredientes, receitas, guardiao
        self.subs = carregar_substituicoes()
        self.llm = llm                       # função prompt -> texto (ou None)
        self.modo = modo or ("llm" if llm else "base")
        self.log: list[str] = []

    # ======================================================== ponto de entrada
    def propor(self, perfil, estoque, feedback, n=6):
        """feedback = {"motivos": [...], "rejeitadas": {nomes}, "aprovadas": {nomes}}"""
        if self.modo == "llm":
            try:
                receitas = self._propor_llm(perfil, estoque, feedback, n)
                if receitas:
                    return receitas
                self.log.append("LLM devolveu lista vazia; usando a base")
            except Exception as e:                       # API fora, JSON quebrado etc.
                self.log.append(f"falha no LLM ({type(e).__name__}); usando a base")
        return self._propor_base(perfil, estoque, feedback, n)

    # ======================================================== modo LLM
    def _ids_permitidos(self, perfil):
        proibidos = self.guardiao.proibidos(perfil) | set(perfil.nao_gosta)
        return [i for i in self.ing if i not in proibidos]

    def montar_prompt(self, perfil, estoque, feedback, n):
        permitidos = self._ids_permitidos(perfil)
        catalogo = "\n".join(f"- {i}: {self.ing[i]['nome']} ({self.ing[i]['categoria']})"
                             for i in permitidos)
        em_casa = ", ".join(f"{i} ({g:.0f} g)" for i, g in estoque.items() if g > 0) or "nada"
        pratos = [r for r in self.rec.values() if r.get("tipo", "prato") == "prato"]
        exemplos = [self._receita_base_para_json(r) for r in pratos[:2]]
        evitar = sorted(feedback["rejeitadas"] | feedback["aprovadas"])
        motivos = "\n".join(f"- {m}" for m in feedback["motivos"]) or "- nenhum ainda"
        return f"""Você é o Montador de um sistema de planejamento de refeições brasileiras.
Proponha {n} receitas caseiras, simples e variadas, para {perfil.pessoas} pessoa(s).

REGRAS OBRIGATÓRIAS
- Use SOMENTE ingredientes desta lista, pelo id exato:
{catalogo}
- Tempo de preparo de no máximo {perfil.tempo_max_min} minutos.
- Quantidades em gramas, realistas para {perfil.pessoas} pessoa(s).
- Priorize o que já está em casa: {em_casa}.
- Região do usuário: {perfil.regiao}. Ingredientes de que gosta: {', '.join(perfil.gosta) or 'não informado'}.
- Não repita estas receitas: {', '.join(evitar) or 'nenhuma'}.

PROBLEMAS DAS RODADAS ANTERIORES (corrija):
{motivos}

Responda APENAS com um array JSON, sem texto antes ou depois, neste formato:
{json.dumps(exemplos, ensure_ascii=False, indent=1)}"""

    def _propor_llm(self, perfil, estoque, feedback, n):
        texto = self.llm(self.montar_prompt(perfil, estoque, feedback, n))
        bruto = json.loads(re.search(r"\[.*\]", texto, re.S).group(0))  # pega só o array
        receitas = []
        for r in bruto:
            try:
                receitas.append({
                    "nome": str(r["nome"]), "porcoes": int(r["porcoes"]),
                    "tempo_min": int(r["tempo_min"]), "preparo": str(r.get("preparo", "")),
                    "ingredientes": [{"id": str(i["id"]), "gramas": float(i["gramas"])}
                                     for i in r["ingredientes"]],
                    "origem": "llm",
                })
            except (KeyError, TypeError, ValueError):
                self.log.append(f"receita do LLM fora do formato descartada: {r!r:.60}")
        self.log.append(f"LLM propôs {len(receitas)} receitas")
        return receitas

    # ======================================================== modo base (sem LLM)
    def _receita_base_para_json(self, r, itens=None, nome=None):
        return {"nome": nome or r["nome"], "porcoes": int(r["porcoes"]),
                "tempo_min": r["tempo_min"], "preparo": "",
                "ingredientes": [{"id": i, "gramas": g} for i, g in (itens or r["itens"]).items()],
                "origem": "base"}

    def _adaptar(self, r, perfil):
        """Troca ingredientes proibidos ou de que a pessoa não gosta. None se não der."""
        evitar = self.guardiao.proibidos(perfil) | set(perfil.nao_gosta)
        proteinas = {i: g for i, g in r["itens"].items() if self.ing[i]["categoria"] == "proteina"}
        if proteinas and max(proteinas, key=proteinas.get) in evitar:
            return None   # a proteína principal define o prato: "frango ensopado" sem frango não serve
        itens, trocas = {}, []
        for i, g in r["itens"].items():
            if i not in evitar:
                itens[i] = itens.get(i, 0) + g
                continue
            sub = next((s for s in self.subs.get(i, [])
                        if s == "remover" or (s not in evitar and s in self.ing)), None)
            if sub is None:
                return None
            if sub == "remover":                       # ex.: bacon/paio só davam sabor
                trocas.append(f"sem {self.ing[i]['nome']}")
                continue
            itens[sub] = itens.get(sub, 0) + g
            trocas.append(f"{self.ing[i]['nome']} → {self.ing[sub]['nome']}")
        if not itens:
            return None
        nome = r["nome"] + (f" (adaptada: {', '.join(trocas)})" if trocas else "")
        return itens, nome, len(trocas)

    def _propor_base(self, perfil, estoque, feedback, n):
        candidatas = []
        for r in self.rec.values():
            if r.get("tipo", "prato") != "prato":      # molhos e acompanhamentos não viram refeição
                continue
            if r["tempo_min"] > perfil.tempo_max_min:  # não propõe o que já se sabe que será vetado
                continue
            adaptada = self._adaptar(r, perfil)
            if adaptada is None:
                continue
            itens, nome, n_trocas = adaptada
            if nome in feedback["rejeitadas"] or nome in feedback["aprovadas"]:
                continue
            total = sum(itens.values())
            cobertura = sum(min(g, estoque.get(i, 0)) for i, g in itens.items()) / total
            candidatas.append((cobertura - 0.15 * n_trocas,          # prefere receitas originais
                               self._receita_base_para_json(r, itens, nome)))
        candidatas.sort(key=lambda t: -t[0])          # mais aproveitamento do estoque primeiro
        self.log.append(f"base propôs {min(n, len(candidatas))} receitas")
        return [c for _, c in candidatas[:n]]

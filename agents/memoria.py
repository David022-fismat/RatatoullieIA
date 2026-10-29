"""
Memória da semana do Avaliador: lembra o que já foi sugerido nos últimos dias para evitar repetição.

O Avaliador usa a memória para calcular a característica "novidade" de cada receita:
  novidade = 1 - (semelhança com a receita mais parecida sugerida nos últimos 7 dias)

Semelhança entre duas receitas:
  - 1,0 se for a mesma receita (mesmo nome, ignorando "(adaptada: ...)");
  - senão, a sobreposição dos ingredientes principais (índice de Jaccard), sem contar temperos e óleo:
        |A ∩ B| / |A ∪ B|        ex.: {arroz, feijão, ovo} × {arroz, feijão, frango} = 2/4 = 0,5

A novidade entra na nota como as outras características (peso "novidade" do perfil, 2 no começo).
Não é veto: uma receita repetida ainda pode aparecer, só perde pontos. Sem memória (memoria=None),
o Avaliador funciona como antes, o que mantém os experimentos reproduzíveis.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent      # pasta principal do projeto
ARQ_MEMORIA = RAIZ / "memoria_semana.json"
CATEGORIAS_IGNORADAS = {"tempero", "gordura"}      # cebola, alho, óleo não tornam pratos "parecidos"
PESO_NOVIDADE = 2.0   # peso inicial: repetir na mesma semana pesa o dobro dos outros critérios (o aprendizado ajusta)


def nome_base(nome):
    return nome.split(" (adaptada")[0].strip().lower()


def principais(receita, ing):
    ids = [i["id"] for i in receita["ingredientes"]] if "ingredientes" in receita else receita["principais"]
    return {i for i in ids if i in ing and ing[i]["categoria"] not in CATEGORIAS_IGNORADAS}


def semelhanca(a, b, ing):
    """a, b: receitas no formato do Montador ou entradas da memória."""
    if nome_base(a["nome"]) == nome_base(b["nome"]):
        return 1.0
    pa, pb = principais(a, ing), principais(b, ing)
    if not pa or not pb:
        return 0.0
    return len(pa & pb) / len(pa | pb)


class MemoriaSemana:
    def __init__(self, ingredientes, arquivo=ARQ_MEMORIA, dias=7, salvar=True):
        self.ing, self.arquivo, self.dias, self.salvar = ingredientes, Path(arquivo), dias, salvar
        self.hoje = None                       # None = data de hoje; dá para fixar (simulação)
        self.entradas = []
        if salvar and self.arquivo.exists():
            self.entradas = json.loads(self.arquivo.read_text(encoding="utf-8"))

    def _hoje(self):
        return self.hoje or date.today()

    def recentes(self):
        limite = self._hoje() - timedelta(days=self.dias - 1)
        return [e for e in self.entradas if limite <= date.fromisoformat(e["data"]) <= self._hoje()]

    def mais_parecida(self, receita):
        """(semelhança 0..1, entrada mais parecida ou None) entre as sugestões da semana."""
        melhor, sim = None, 0.0
        for e in self.recentes():
            s = semelhanca(receita, e, self.ing)
            if s > sim:
                melhor, sim = e, s
        return sim, melhor

    def registrar(self, receitas):
        hoje = self._hoje().isoformat()
        for r in receitas:
            self.entradas.append({"data": hoje, "nome": r["nome"],
                                  "principais": sorted(principais(r, self.ing))})
        limite = self._hoje() - timedelta(days=30)          # não guarda mais que 30 dias
        self.entradas = [e for e in self.entradas if date.fromisoformat(e["data"]) >= limite]
        self._persistir()

    def limpar(self):
        self.entradas = []
        self._persistir()

    def _persistir(self):
        if self.salvar:
            self.arquivo.write_text(json.dumps(self.entradas, ensure_ascii=False, indent=1), encoding="utf-8")

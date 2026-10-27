# Protótipo RatatouilleIA – agentes de planejamento de refeições

## Rodar

    pip install -r requirements.txt
    python demo_montador_avaliador.py        # Montador + Avaliador (base e LLM simulado)
    python demo_montador_avaliador.py --llm  # LLM real (precisa de ANTHROPIC_API_KEY)
    python demo_avaliador.py                 # só o Avaliador
    python demo.py                           # protótipo inicial (Leitor, Planejador, Comprador)

## Base de conhecimento (kb/)

A base é GERADA a partir de `fontes/`. Não edite `kb/` à mão: edite as fontes ou o script e rode

    python scripts/construir_base.py

| Arquivo em fontes/ | Origem |
|---|---|
| receitas_ministerio.csv | 15 receitas de *Na Cozinha com as Frutas, Legumes e Verduras* (Ministério da Saúde/UFMG, 2016, licença CC BY-NC-SA 4.0) e 10 de *Preparações Regionais Saudáveis* (Ministério da Saúde, 2010), em medidas caseiras |
| receitas_llm.csv | receitas geradas por IA para lacunas da base, aprovadas pelo Avaliador; coluna `revisado_pelo_grupo` |
| lote_inicial_llm.json | o lote inicial de receitas de IA (gerado pelo Claude), antes da validação |
| taco_food.csv, taco_nutrients.csv | TACO 4ª ed. (NEPA/Unicamp), via repositório github.com/raulfdm/taco-api |
| *_grupo.csv | receitas e ingredientes escritos pelo grupo |
| transcricao_bh_2013.csv, cardapios_campinas.csv… | merenda escolar (BH e Campinas): desligadas por padrão |

Medidas caseiras ("½ xícara", "2 colheres de sopa", "1 cebola") viram gramas em `scripts/medidas.py`,
com valores de referência aproximados.

### Gerar mais receitas com o LLM

    python scripts/gerar_receitas_llm.py                      # usa a API (ANTHROPIC_API_KEY)
    python scripts/gerar_receitas_llm.py --de-arquivo X.json  # valida um lote já gerado

As aprovadas pelo Avaliador vão para `fontes/receitas_llm.csv` com `revisado_pelo_grupo=nao`.
Revisem, troquem para `sim` e rodem `python scripts/construir_base.py`. Antes da entrega final,
usem `INCLUIR_LLM_NAO_REVISADAS = False` no script para só entrar o que foi revisado.

O script gera `kb/RELATORIO_BASE.md` com contagens, divergências encontradas e pendências.

## Arquivos dos agentes

| Arquivo | Papel |
|---|---|
| montador.py | propõe receitas (LLM ou base + substituições) |
| avaliador.py | valida, pontua e calcula nutrientes (TACO) |
| planejamento.py | laço de rodadas entre os dois |
| agentes.py | Leitor de nota, Guardião, Planejador, Comprador (protótipo inicial) |

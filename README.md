# Protótipo RatatouilleIA – agentes de planejamento de refeições

## Usar o agente no navegador (mais fácil)

    pip install -r requirements.txt
    streamlit run app.py

Abre uma página com o perfil na barra lateral e três abas: **Planejar** (estoque → cardápio, "eu faria",
lista de compras), **Conversa com o agente** (o Orquestrador com LLM; cole a chave grátis do Gemini na
própria página) e **Memória da semana** (o que o Avaliador lembra, com um botão para simular os dias).

Para publicar na internet e mandar o link para os mentores: entre em share.streamlit.io com a conta do
GitHub, escolha este repositório e o arquivo `app.py`. Em *Advanced settings → Secrets*, coloque
`GEMINI_API_KEY = "sua-chave"` para a conversa funcionar sem ninguém colar chave.

### Benchmark do Orquestrador (modo seco)

`Orquestrador.decidir(mensagem)` mostra qual ferramenta o LLM escolheria, com os argumentos, **sem
executar nada** (não muda perfil, estoque nem memória). Usos:

    python scripts/bench_orquestrador.py                 # roda os casos de bench/casos.json com o LLM da chave
    python scripts/bench_orquestrador.py --repeticoes 3  # repete cada caso (o LLM varia)
    python scripts/bench_orquestrador.py --simulado      # só para testar o script, sem chave

Mostra, para cada mensagem, a ferramenta esperada e a escolhida, e calcula a taxa de acerto (só a
ferramenta, e ferramenta + argumentos). Grava um CSV em `resultados/` com data e modelo, para comparar
modelos e versões das instruções. No chat, o modo seco liga com `/seco` (terminal) ou com a chave
"Modo teste" (app).

### Memória da semana (memoria.py)

O Avaliador lembra o que foi sugerido nos últimos 7 dias. Cada receita ganha a característica
`novidade` = 1 − semelhança com a mais parecida da semana (mesma receita = 1; senão, sobreposição dos
ingredientes principais). Ela entra na nota com peso 2 no começo, e o aprendizado ajusta esse peso.
O Montador também vê a memória e propõe receitas novas primeiro. `python demo_memoria.py` mostra o
mesmo pedido em 4 dias seguidos, sem e com memória. Sem memória, tudo funciona como antes (os
experimentos não mudam). `python agente_interativo.py --esquecer` apaga a memória.

## Usar o agente no terminal

    python agente_interativo.py           # pergunta perfil e estoque, mostra o cardápio e aprende com o retorno
    python agente_interativo.py --llm     # mesmo, com o Montador usando LLM (precisa de ANTHROPIC_API_KEY)
    python agente_interativo.py --novo    # refaz o perfil (fica salvo em perfil.json)
    python agente_interativo.py --chat    # conversa livre: o Orquestrador (LLM) decide quais agentes chamar
    python demo_orquestrador.py  # o Orquestrador decidindo, com LLM simulado (não precisa de chave)

### Orquestrador (orquestrador.py)

Agente com LLM e *tool calling*. A cada mensagem ele escolhe quais ferramentas chamar, olha o
resultado e decide o próximo passo (atualizar o estoque, planejar, relaxar o tempo, montar a lista de
compras, otimizar no orçamento, registrar o retorno). As ferramentas são os outros agentes:

| Ferramenta | Agente |
|---|---|
| atualizar_estoque, ver_perfil_e_estoque | leitor de ingredientes + estado compartilhado |
| atualizar_preferencias | perfil (só ADICIONA restrições) |
| planejar_refeicoes | Montador + Avaliador (laço de rodadas) |
| lista_de_compras | soma o que falta, com preço estimado |
| planejar_com_orcamento | Comprador (PuLP) |
| registrar_retorno | aprendizado dos pesos |

Provedor de LLM (`provedores.py`): basta definir UMA chave no terminal.

| Provedor | Custo | Onde criar a chave | Variável |
|---|---|---|---|
| Google Gemini | cota grátis | aistudio.google.com/apikey | `GEMINI_API_KEY` |
| Groq | cota grátis | console.groq.com/keys | `GROQ_API_KEY` |
| Anthropic | pago | console.anthropic.com | `ANTHROPIC_API_KEY` |

Para trocar o modelo: `export MODELO_ORQUESTRADOR=...`. Para forçar um provedor: `export LLM_PROVEDOR=groq`.

Limites por construção: o Guardião lê a mensagem antes do LLM; não há ferramenta para remover
restrição; receitas só saem do Avaliador; no máximo 8 ferramentas por mensagem. Cada decisão vai
para `logs/decisoes.jsonl`.

## Demonstrações

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

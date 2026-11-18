# Protótipo RatatouilleIA – agentes de planejamento de refeições

## Organização das pastas

| Pasta | O que tem |
|---|---|
| `agents/` | os agentes: `agentes.py` (perfil, Guardião, Leitor de nota, Comprador), `montador.py`, `avaliador.py`, `planejamento.py` (laço e aprendizado), `memoria.py`, `orquestrador.py`, `provedores.py` (Gemini, Groq, Anthropic) |
| `layout/` | as interfaces: `app.py` (navegador) e `agente_interativo.py` (perguntas no terminal e `--chat`) |
| `demos/` | demonstrações de cada parte, com dados fixos: `python demos/demo_orquestrador.py` |
| `scripts/` | montar a base, gerar receitas com LLM e rodar os experimentos |
| `servicos/` | APIs HTTP: `api_dri.py` (calculadora DRI) |
| `mocks/` | ambientes do Mockoon que imitam as APIs: `dri.json` |
| `tests/` | testes automáticos: `python -m pytest tests -q` |
| `docs/` | explicações longas (ex.: `avaliador_bandit_explicado.pdf`) |
| `kb/`, `fontes/`, `resultados/` | base de conhecimento gerada, fontes originais e resultados dos experimentos |
| `app.py` | só chama `layout/app.py` (é o arquivo que o Streamlit Cloud procura) |

Os arquivos de uso pessoal (`perfil.json`, `estoque.json`, `memoria_semana.json`, `logs/`) ficam na pasta
principal e não vão para o GitHub. Dentro de `agents/`, os arquivos se importam com `from .modulo import ...`;
de fora, com `from agents.modulo import ...`.

## Usar o agente no navegador (mais fácil)

    pip install -r requirements.txt
    streamlit run app.py

Abre uma página com o perfil na barra lateral e três abas: **Planejar** (o sistema mostra opções de
refeição diferentes entre si; a pessoa clica em "Quero esta" e o agente aprende com a escolha),
**Conversa com o agente** (o Orquestrador com LLM; cole a chave grátis do Gemini na
própria página) e **Memória da semana** (o que o Avaliador lembra, com um botão para simular os dias).

Para publicar na internet e mandar o link para os mentores: entre em share.streamlit.io com a conta do
GitHub, escolha este repositório e o arquivo `app.py`. Em *Advanced settings → Secrets*, coloque
`GEMINI_API_KEY = "sua-chave"` para a conversa funcionar sem ninguém colar chave.

### Memória da semana (agents/memoria.py)

O Avaliador lembra o que a pessoa escolheu nos últimos 7 dias. Cada receita ganha a característica
`novidade` = 1 − semelhança com a mais parecida da semana (mesma receita = 1; senão, sobreposição dos
ingredientes principais). Ela entra na nota com peso 2 no começo, e o aprendizado ajusta esse peso.
O Montador também vê a memória e propõe receitas novas primeiro. `python demos/demo_memoria.py` mostra o
mesmo pedido em 4 dias seguidos, sem e com memória. Sem memória, tudo funciona como antes (os
experimentos não mudam). `python layout/agente_interativo.py --esquecer` apaga a memória.

## Usar o agente no terminal

    python layout/agente_interativo.py           # pergunta perfil e estoque, mostra o cardápio e aprende com o retorno
    python layout/agente_interativo.py --llm     # mesmo, com o Montador usando LLM (precisa de ANTHROPIC_API_KEY)
    python layout/agente_interativo.py --novo    # refaz o perfil (fica salvo em perfil.json)
    python layout/agente_interativo.py --chat    # conversa livre: o Orquestrador (LLM) decide quais agentes chamar
    python demos/demo_orquestrador.py  # o Orquestrador decidindo, com LLM simulado (não precisa de chave)

### Orquestrador (agents/orquestrador.py)

Agente com LLM e *tool calling*. A cada mensagem ele escolhe quais ferramentas chamar, olha o
resultado e decide o próximo passo (oferecer opções, relaxar o tempo, mostrar outras opções, registrar a
escolha). As ferramentas são os outros agentes:

| Ferramenta | Agente |
|---|---|
| ver_perfil | perfil + memória da semana |
| atualizar_preferencias | perfil (só ADICIONA restrições) |
| opcoes_de_refeicao | Montador + Avaliador (laço de rodadas), com opções variadas (uma por proteína principal) |
| escolher_receita | aprendizado dos pesos (escolhida × outras opções) + memória da semana |

O fluxo é por **opções**: não é preciso informar o que tem em casa. O Comprador (orçamento) e o leitor de
estoque continuam em `agents/agentes.py`, mas não são mais ferramentas do Orquestrador.

Provedor de LLM (`agents/provedores.py`): basta definir UMA chave no terminal.

| Provedor | Custo | Onde criar a chave | Variável |
|---|---|---|---|
| Google Gemini | cota grátis | aistudio.google.com/apikey | `GEMINI_API_KEY` |
| Groq | cota grátis | console.groq.com/keys | `GROQ_API_KEY` |
| Anthropic | pago | console.anthropic.com | `ANTHROPIC_API_KEY` |

Para trocar o modelo: `export MODELO_ORQUESTRADOR=...`. Para forçar um provedor: `export LLM_PROVEDOR=groq`.

Limites por construção: o Guardião lê a mensagem antes do LLM; não há ferramenta para remover
restrição; receitas só saem do Avaliador; no máximo 8 ferramentas por mensagem. Cada decisão vai
para `logs/decisoes.jsonl`.

### Substituir um ingrediente (mapa SOM da TBCA)

Na aba **Planejar**, cada opção tem o painel **🔄 Substituir um ingrediente**:

1. a pessoa escolhe o ingrediente e clica em **Achar substitutos**;
2. o Substituidor (`agents/substituidor.py`) acha a **gaveta** do ingrediente no mapa SOM 10×10 treinado com os
   2.556 **alimentos** da **TBCA** (37 nutrientes por 100 g, normalizados por Min-Max; as 3.112 receitas da
   TBCA ficam de fora) e ordena os outros alimentos
   pela distância entre as gavetas (no empate, pela distância entre os nutrientes);
3. ficam só os do mesmo grupo do prato (proteína pode virar leguminosa), que existem na base do app e que
   respeitam as restrições (alérgenos e dietas da TBCA) e os "não gosta" do perfil;
4. ao clicar em **Trocar**, a receita troca o ingrediente por uma quantidade com as **mesmas calorias** e
   volta para o **Avaliador**, que aprova (e recalcula a nota) ou explica por que não aprovou.

| Arquivo | O que é |
|---|---|
| fontes/TBCA_dados_modelo.xlsx | TBCA tratada: nutrientes limpos e normalizados, NOVA, Nutri-Score, alérgenos e dietas |
| scripts/limpar_receitas_tbca.py | tira as receitas (salada, sopa, sanduíche, papa, "c/ batata"...) → lista do que saiu em `kb/som/tbca_receitas_removidas.csv` |
| scripts/ligar_ingredientes_tbca.py | liga os ingredientes do app aos alimentos da TBCA → `kb/som/ingrediente_tbca.csv` (revisar) |
| scripts/preparar_tbca_som.py | só alimentos, Min-Max refeito sem as receitas → `kb/som/tbca_som.csv` e `kb/som/parametros_minmax.csv` |
| scripts/treinar_som.py | treina o mapa → `kb/som/som_tbca.npz` (precisa de `pip install minisom openpyxl scikit-learn`) |
| scripts/atualizar_som.py | roda os quatro scripts acima, na ordem |
| agents/substituidor.py | usa o mapa salvo; o app precisa só de numpy e pandas |
| agents/orquestrador.py | `substitutos()` e `trocar_na_opcao()` |

O mapa já vem treinado. Para refazer tudo: `python scripts/atualizar_som.py`. Se uma regra de receita tirar
um alimento que deveria ficar, ajuste `limpar_receitas_tbca.py` e confira `kb/som/tbca_receitas_removidas.csv`.
Os nutrientes das receitas (Avaliador) continuam vindo de `kb/ingredientes.csv`; a TBCA entra na substituição.

## Cronograma por ingredientes (sem receitas)

Para cada refeição do dia, o agente mostra **3 opções**. Cada opção é um prato montado com ingredientes, um de
cada grupo, com as **gramas calculadas para bater as metas da calculadora DRI**. A pessoa escolhe uma, e o
Avaliador aprende com isso.

| refeição | grupos de cada opção |
|---|---|
| café da manhã, lanche | carboidrato + proteína (laticínio, ovo, frios) + fruta |
| almoço, jantar | proteína + carboidrato + leguminosa (feijão) + legumes + fruta |

    calculadora DRI (API ou Mockoon) -> Montador -> Avaliador -> 3 opções -> escolha -> o bandit aprende

| Arquivo | O que faz |
|---|---|
| agents/calculadora_dri.py | metas do dia e de cada refeição para adultos: energia pelas equações EER de 2023 (as da calculadora DRI do USDA), proteína, carboidrato, gordura, fibra, sódio e água pelas DRI. Menores de 19 anos, gestantes e lactantes são encaminhados a um profissional |
| servicos/api_dri.py | a calculadora como API HTTP (`POST /dri`, `GET /saude`), só com a biblioteca padrão |
| mocks/dri.json | o **Mockoon** imitando essa API, com cenários de teste (gerado por `scripts/gerar_mock_dri.py`) |
| agents/cliente_dri.py | como o Montador pede as metas: chama a API em `DRI_API_URL`; se ela cair, calcula localmente |
| kb/cronograma/despensa.csv | os alimentos que se combinam, por região, refeição e grupo: os mais comidos na POF 2017–2018, com a porção típica, e os nutrientes da TBCA sem receitas (gerado por `scripts/preparar_despensa.py`) |
| agents/montador_ingredientes.py | todas as combinações da refeição, com as gramas ajustadas à energia e à proteína da meta |
| agents/avaliador_ingredientes.py | trava (restrições, não gosta, sódio), nota de bem-estar e bandit (LinUCB) que escolhe as 3 opções e aprende com a escolha. O método está explicado em `docs/avaliador_bandit_explicado.pdf` |
| agents/cronograma.py | junta tudo: `Cronograma(...).dia()` e `.escolher(refeicao, posicao)` |

### Rodar

    pip install -r requirements.txt
    npx @mockoon/cli start --data mocks/dri.json      # terminal 1: o mock da API DRI na porta 3001
    python demos/demo_cronograma.py                   # terminal 2
    python demos/demo_cronograma.py --regiao Sul --restricoes vegetariano --nao-gosta tomate
    python demos/demo_cronograma.py --aprender        # 20 almoços simulados: o que o bandit aprende

No lugar do mock, dá para subir a calculadora de verdade na mesma porta: `python -m servicos.api_dri`.
Sem nenhuma das duas, use `--local`.

### Mockoon

O Mockoon serve uma API falsa a partir de um arquivo. O `mocks/dri.json` responde como a API da calculadora
DRI, para quem trabalha no Montador, no Avaliador ou na interface não depender da calculadora real estar no ar.

* **No aplicativo (Mockoon Desktop):** *Open environment* → `mocks/dri.json` → *Start*. As rotas, as respostas
  e as regras de cada cenário aparecem na tela.
* **No terminal:** `npx @mockoon/cli start --data mocks/dri.json` (precisa do Node.js).

| pedido | resposta do mock |
|---|---|
| `GET /saude` | 200 `{"status": "ok"}` |
| `POST /dri` com `"sexo": "F"` | 200, metas de uma mulher de exemplo (30 anos, 163 cm, 62 kg, pouco ativa) |
| `POST /dri` com outro sexo | 200, metas de um homem de exemplo (35 anos, 175 cm, 78 kg, pouco ativo) |
| `POST /dri` com idade até 18, `gestante` ou `amamentando` | 422, encaminhamento a um profissional |
| `POST /dri` sem algum campo obrigatório | 422, campos faltando |
| cabeçalho `X-Cenario: erro` | 500 (o cliente calcula as metas localmente) |
| cabeçalho `X-Cenario: lento` | resposta depois de 8 s (o cliente desiste em 5 s e calcula localmente) |

As metas do mock são **fixas**: servem para testar o fluxo, não para a pessoa real. As respostas de sucesso
são geradas pela calculadora de verdade, então o formato é sempre o mesmo da API. Se o formato mudar, rode
`python scripts/gerar_mock_dri.py` de novo.

Corpo do `POST /dri`:

    {"sexo": "F", "idade": 30, "altura_cm": 163, "peso_kg": 62, "atividade": "pouco_ativo",
     "gestante": false, "amamentando": false}

`atividade`: `inativo`, `pouco_ativo`, `ativo` ou `muito_ativo`.

### Testes

    pip install pytest
    python -m pytest tests -q

Com o Mockoon (ou a API) no ar, o teste do contrato também roda; sem, ele é pulado.

## Demonstrações

    pip install -r requirements.txt
    python demos/demo_montador_avaliador.py        # Montador + Avaliador (base e LLM simulado)
    python demos/demo_montador_avaliador.py --llm  # LLM real (precisa de ANTHROPIC_API_KEY)
    python demos/demo_avaliador.py                 # só o Avaliador
    python demos/demo.py                           # protótipo inicial (Leitor, Planejador, Comprador)
    python demos/demo_cronograma.py                # cronograma por ingredientes (ver acima)
    python demos/demo_substituicao.py              # mapa SOM direto (ex.: python demos/demo_substituicao.py carne --vegetariano)

## Base de conhecimento (kb/)

A base é GERADA a partir de `fontes/`. Não edite `kb/` à mão: edite as fontes ou o script e rode

    python scripts/construir_base.py

| Arquivo em fontes/ | Origem |
|---|---|
| receitas_ministerio.csv | 15 receitas de *Na Cozinha com as Frutas, Legumes e Verduras* (Ministério da Saúde/UFMG, 2016, licença CC BY-NC-SA 4.0) e 10 de *Preparações Regionais Saudáveis* (Ministério da Saúde, 2010), em medidas caseiras |
| receitas_ms_texto.csv | as **124 receitas completas** (ingredientes em texto + **modo de preparo**) dos dois livros do Ministério, extraídas dos PDFs por `scripts/extrair_livros_ms.py` |
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

### Modo de preparo e base de texto do RAG

- `kb/receitas.csv` tem a coluna `preparo`. O app mostra o modo de preparo de cada receita do cardápio
  (botão "Modo de preparo"), e o Orquestrador recebe o texto para responder "como faço?".
- `kb/receitas_rag.csv` é a base de **texto** para o RAG: toda receita com modo de preparo (124 dos
  livros + as do LLM). A coluna `id_base` diz quais também estão na base operacional (com gramas);
  as outras servem só de referência para a LLM (ainda não têm ingredientes em gramas).
- Receitas do grupo ainda sem preparo: escrevam na coluna `preparo` de `fontes/receitas_grupo.csv`.
- Para refazer a extração dos PDFs (opcional, o CSV já vem pronto):

      pip install pdfplumber
      python scripts/extrair_livros_ms.py Na_cozinha....pdf preparacoes_regionais....pdf

Por que não fazer scraping de sites de receitas: o texto do modo de preparo é obra autoral (Lei
9.610/98, sem exceção para mineração de texto) e os termos de uso desses sites costumam proibir coleta
automatizada. Os livros do Ministério são públicos e alinhados ao Guia Alimentar.

## Arquivos dos agentes

| Arquivo | Papel |
|---|---|
| agents/montador.py | propõe receitas (LLM ou base + substituições) |
| agents/avaliador.py | valida, pontua e calcula nutrientes (TACO) |
| agents/planejamento.py | laço de rodadas entre os dois |
| agents/agentes.py | Leitor de nota, Guardião, Planejador, Comprador (protótipo inicial) |

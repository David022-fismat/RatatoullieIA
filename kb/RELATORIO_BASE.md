# Relatório da base de conhecimento

- Receitas: 50 no total (8 acompanhamentos)
  - grupo: 12
  - Ministério da Saúde: 25
  - geradas pelo LLM: 13 (13 pendentes de revisão)
- Ingredientes: 81 (75 com nutrientes da TACO)

## Receitas do Ministério da Saúde

| Receita | Região | Fonte | Tipo | g por pessoa |
|---|---|---|---|---|
| Farofa de Legumes | Brasil | NCFLV | acompanhamento | 126 |
| Purê de Legumes | Brasil | NCFLV | acompanhamento | 237 |
| Suflê de Chuchu | Brasil | NCFLV | prato | 120 |
| Bolinho Assado de Chuchu | Brasil | NCFLV | prato | 105 |
| Mamão Verde Refogado | Brasil | NCFLV | acompanhamento | 223 |
| Kibe de Forno com Abóbora | Brasil | NCFLV | prato | 110 |
| Charuto de Repolho | Brasil | NCFLV | prato | 151 |
| Panqueca Verde | Brasil | NCFLV | prato | 159 |
| Trouxinha de Couve com Carne Moída e Angu | Sudeste | NCFLV | prato | 271 |
| Rocambole de Moranga com Batata | Brasil | NCFLV | prato | 210 |
| Torta de Tomate | Brasil | NCFLV | prato | 135 |
| Almôndega com Jiló | Sudeste | NCFLV | prato | 82 |
| Torta de Arroz com Recheio de Tomate | Brasil | NCFLV | prato | 320 |
| Suflê de Cenoura | Brasil | NCFLV | prato | 162 |
| Virado de Quiabo | Sudeste | NCFLV | prato | 224 |
| Arroz com Pupunha | Norte | PRS | acompanhamento | 113 |
| Caldeirada de Peixe com Chicória | Norte | PRS | prato | 216 |
| Galinhada com Pequi | Centro-Oeste | PRS | prato | 401 |
| Cozidão Maranhense | Nordeste | PRS | prato | 169 |
| Refogado de Carne com Palma | Nordeste | PRS | prato | 111 |
| Vatapá de Inhame | Nordeste | PRS | acompanhamento | 81 |
| Arroz com Fibra de Caju | Nordeste | PRS | acompanhamento | 105 |
| Fígado com Jiló | Sudeste | PRS | prato | 162 |
| Angu com Espinafre | Sudeste | PRS | acompanhamento | 92 |
| Virado de Vagem | Sudeste | PRS | acompanhamento | 35 |

## Receitas geradas pelo LLM

| Receita | Lacuna que cobre | Revisada pelo grupo |
|---|---|---|
| Cuscuz com ovo mexido e tomate | rápida para quem mora sozinho (1 porção, até 20 min) | pendente |
| Macarrão com sardinha e tomate | rápida para quem mora sozinho (1 porção, até 20 min) | pendente |
| Frango em cubos com abobrinha | rápida para quem mora sozinho (1 porção, até 20 min) | pendente |
| Feijão preto com abóbora e couve | vegetariana com leguminosa | pendente |
| Grão-de-bico refogado com tomate e espinafre | vegetariana com leguminosa | pendente |
| Escondidinho de mandioca com feijão | vegetariana com leguminosa | pendente |
| Carne moída com legumes | marmita para a semana que congela bem (4 porções) | pendente |
| Frango desfiado com milho e cenoura | marmita para a semana que congela bem (4 porções) | pendente |
| Polenta mole com molho de carne moída | baixo custo | pendente |
| Sopa de feijão com macarrão | baixo custo | pendente |
| Peixe assado com batata e tomate | sem lactose e sem glúten | pendente |
| Baião de dois simples | regional nordestina do dia a dia | pendente |
| Cuscuz nordestino com ovo e legumes | regional nordestina do dia a dia | pendente |

## Conversão de medidas caseiras: avisos

- Virado de Quiabo: sem rendimento; estimadas 2 porções (250 g cada)

## Ingredientes sem correspondência na TACO

- trigo_quibe
- molho_soja
- vinagre
- hortela
- vinagreira
- palma

## Pendências para o grupo

- Revisar as receitas do LLM e marcar revisado_pelo_grupo=sim em fontes/receitas_llm.csv; antes da entrega, usar INCLUIR_LLM_NAO_REVISADAS = False.
- Medidas caseiras viraram gramas por valores de referência aproximados (scripts/medidas.py); refinar com a tabela de medidas referidas do IBGE (POF 2008-2009).
- As receitas do Ministério não informam tempo de preparo: foi estimado por tipo de prato.
- Preços são estimativas: trocar por DIEESE ou levantamento em mercado.
- Transcrições feitas por leitura automática dos PDFs: conferir algumas com o original.

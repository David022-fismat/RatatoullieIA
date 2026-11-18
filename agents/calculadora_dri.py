"""
Calculadora DRI: metas de energia e macronutrientes do dia e de cada refeição, para adultos.

É a mesma base da calculadora do USDA (https://www.nal.usda.gov/human-nutrition-and-food-safety/dri-calculator):
as Dietary Reference Intakes das National Academies.

  * Energia: equações de gasto energético total (EER) de 2023, uma por sexo e nível de atividade
    (National Academies, "Dietary Reference Intakes for Energy", 2023, Tabela S-1). Idade em anos,
    altura em cm, peso em kg, resultado em kcal/dia.
  * Proteína: RDA de 0,8 g/kg/dia; faixa aceitável (AMDR) de 10% a 35% da energia.
  * Carboidrato: RDA de 130 g/dia; AMDR de 45% a 65% da energia.
  * Gordura: AMDR de 20% a 35% da energia.
  * Fibra: AI de 14 g a cada 1.000 kcal.
  * Sódio: reduzir se passar de 2.300 mg/dia (CDRR, 2019).
  * Água total: AI de 3,7 L (homens) e 2,7 L (mulheres).
  * Gordura saturada e açúcar de adição abaixo de 10% da energia: vêm das Dietary Guidelines for Americans
    e do Guia Alimentar, não das DRI (a calculadora do USDA não traz esses limites).

Fora do escopo (devolve ForaDoEscopo, e o app deve encaminhar para um profissional):
  menores de 19 anos, gestantes e lactantes. Pessoas abaixo do peso ou com obesidade recebem as metas,
  mas com um aviso, porque as equações estimam a energia para MANTER o peso atual.

Uso:
    from agents.calculadora_dri import calcular_dri
    calcular_dri(sexo="F", idade=30, altura_cm=165, peso_kg=62, atividade="pouco_ativo")
"""
from __future__ import annotations

# (constante, idade, altura_cm, peso_kg) — Tabela S-1, adultos de 19 anos ou mais
EER_2023 = {
    ("M", "inativo"):     (753.07, -10.83, 6.50, 14.10),
    ("M", "pouco_ativo"): (581.47, -10.83, 8.30, 14.94),
    ("M", "ativo"):       (1004.82, -10.83, 6.52, 15.91),
    ("M", "muito_ativo"): (-517.88, -10.83, 15.61, 19.11),
    ("F", "inativo"):     (584.90, -7.01, 5.72, 11.71),
    ("F", "pouco_ativo"): (575.77, -7.01, 6.60, 12.14),
    ("F", "ativo"):       (710.25, -7.01, 6.54, 12.34),
    ("F", "muito_ativo"): (511.83, -7.01, 9.07, 12.56),
}
ATIVIDADES = ("inativo", "pouco_ativo", "ativo", "muito_ativo")

# como a energia do dia se divide entre as refeições do cronograma (soma 1)
REPARTICAO = {"cafe_da_manha": 0.20, "almoco": 0.35, "lanche": 0.15, "jantar": 0.30}

# metas usadas para PLANEJAR (dentro das faixas AMDR): 15% proteína, 55% carboidrato, 30% gordura
ALVO_PROTEINA, ALVO_CARBOIDRATO, ALVO_GORDURA = 0.15, 0.55, 0.30

REFERENCIAS = [
    "National Academies (2023). Dietary Reference Intakes for Energy — equações EER, Tabela S-1.",
    "Institute of Medicine (2005). DRI for Energy, Carbohydrate, Fiber, Fat, Fatty Acids, Cholesterol, "
    "Protein, and Amino Acids — RDA, AMDR e AI de fibra.",
    "National Academies (2019). DRI for Sodium and Potassium — CDRR de sódio.",
    "Institute of Medicine (2005). DRI for Water, Potassium, Sodium, Chloride, and Sulfate — AI de água.",
]


class ForaDoEscopo(ValueError):
    """Perfil para o qual a calculadora não dá metas (menor de 19 anos, gestante, lactante)."""


def _validar(sexo, idade, altura_cm, peso_kg, atividade, gestante, amamentando):
    if gestante or amamentando:
        raise ForaDoEscopo("Gestação e amamentação mudam muito as necessidades: procure um nutricionista "
                           "ou o pré-natal para ter metas individuais.")
    if sexo not in ("M", "F"):
        raise ValueError("sexo deve ser 'M' ou 'F'")
    if atividade not in ATIVIDADES:
        raise ValueError(f"atividade deve ser uma de: {', '.join(ATIVIDADES)}")
    if idade < 19:
        raise ForaDoEscopo("As metas para menores de 19 anos incluem a energia do crescimento e não são "
                           "calculadas aqui: procure um nutricionista ou pediatra.")
    if idade > 120 or not 100 <= altura_cm <= 250 or not 30 <= peso_kg <= 300:
        raise ValueError("idade, altura ou peso fora de uma faixa plausível")


def classificar_imc(imc):
    if imc < 18.5:
        return "baixo peso"
    if imc < 25:
        return "eutrofia"
    if imc < 30:
        return "sobrepeso"
    return "obesidade"


def calcular_dri(sexo: str, idade: float, altura_cm: float, peso_kg: float, atividade: str,
                 gestante: bool = False, amamentando: bool = False, reparticao: dict | None = None) -> dict:
    """Metas do dia e por refeição. Levanta ForaDoEscopo ou ValueError se o perfil não serve."""
    sexo = str(sexo).upper()[:1]
    _validar(sexo, idade, altura_cm, peso_kg, atividade, gestante, amamentando)
    a, b_idade, c_altura, d_peso = EER_2023[(sexo, atividade)]
    kcal = a + b_idade * idade + c_altura * altura_cm + d_peso * peso_kg
    imc = peso_kg / (altura_cm / 100) ** 2

    proteina_rda = 0.8 * peso_kg
    dia = {
        "energia_kcal": round(kcal),
        "proteina_g": {"rda": round(proteina_rda, 1),
                       "min": round(max(proteina_rda, 0.10 * kcal / 4), 1), "max": round(0.35 * kcal / 4, 1),
                       "meta": round(max(proteina_rda, ALVO_PROTEINA * kcal / 4), 1)},
        "carboidrato_g": {"rda": 130, "min": round(max(130, 0.45 * kcal / 4), 1), "max": round(0.65 * kcal / 4, 1),
                          "meta": round(max(130, ALVO_CARBOIDRATO * kcal / 4), 1)},
        "gordura_g": {"min": round(0.20 * kcal / 9, 1), "max": round(0.35 * kcal / 9, 1),
                      "meta": round(ALVO_GORDURA * kcal / 9, 1)},
        "fibra_g": round(14 * kcal / 1000, 1),
        "sodio_mg_max": 2300,
        "gordura_saturada_g_max": round(0.10 * kcal / 9, 1),
        "acucar_adicao_g_max": round(0.10 * kcal / 4, 1),
        "agua_l": 3.7 if sexo == "M" else 2.7,
    }

    reparticao = reparticao or REPARTICAO
    refeicoes = {}
    for nome, fracao in reparticao.items():
        refeicoes[nome] = {
            "fracao": fracao,
            "energia_kcal": round(fracao * kcal),
            "proteina_g": round(fracao * dia["proteina_g"]["meta"], 1),
            "carboidrato_g": round(fracao * dia["carboidrato_g"]["meta"], 1),
            "gordura_g": round(fracao * dia["gordura_g"]["meta"], 1),
            "gordura_g_max": round(fracao * dia["gordura_g"]["max"], 1),
            "fibra_g": round(fracao * dia["fibra_g"], 1),
            "sodio_mg_max": round(fracao * dia["sodio_mg_max"]),
        }

    avisos = []
    classe = classificar_imc(imc)
    if classe in ("baixo peso", "obesidade"):
        avisos.append(f"IMC na faixa de {classe}: as equações estimam a energia para manter o peso atual. "
                      "Para ganhar ou perder peso, procure um nutricionista.")
    return {
        "fonte": "calculadora DRI (equações EER 2023)",
        "entrada": {"sexo": sexo, "idade": idade, "altura_cm": altura_cm, "peso_kg": peso_kg,
                    "atividade": atividade},
        "imc": round(imc, 1),
        "classificacao_imc": classe,
        "dia": dia,
        "refeicoes": refeicoes,
        "avisos": avisos,
        "referencias": REFERENCIAS,
    }

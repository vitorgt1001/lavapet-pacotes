"""
catalogo.py
------------------------------------------------------------
Dados fixos usados nos menus (dropdowns) do app: condomínios, serviços
e portes. Vem direto das tabelas de preço do prompt do WhatsApp
(Fluxo_B_atualizado.md), só pra facilitar o preenchimento — o valor do
serviço não é travado por aqui, você sempre pode digitar/ajustar o valor
real cobrado na hora de cadastrar um pacote (por causa de descontos,
promoções etc.).
"""

CONDOMINIOS = [
    "Humanari",
    "Vivaz Rio Bonito",
    "Vila 11 Pinheiros",
    "Vila 11 Vila Mariana",
    "Ventana",
]

SERVICOS = [
    "Banho",
    "Tosa Completa Máquina",
    "Tosa Completa Tesoura",
    "Tosa Higiênica",
    "Hidratação",
    "Escovação de Dente",
    "Remoção de Subpelo",
    "SpaPet",  # exclusivo Ventana
]

PORTES = ["P", "M", "G", "GG"]

# Preço de referência por condomínio/serviço/porte, só como sugestão
# inicial no formulário "Novo Pacote" — não é usado pra nenhum cálculo
# automático de cobrança.
PRECOS_REFERENCIA = {
    "Humanari": {
        "Banho": {"P": 59, "M": 79, "G": 99, "GG": 119},
        "Tosa Completa Máquina": {"P": 129, "M": 149, "G": 179},
        "Tosa Completa Tesoura": {"P": 169, "M": 189, "G": 229},
        "Tosa Higiênica": 25,
        "Hidratação": 39,
        "Escovação de Dente": 5,
        "Remoção de Subpelo": 35,
    },
    "Vivaz Rio Bonito": {
        "Banho": {"P": 54, "M": 74, "G": 94, "GG": 114},
        "Tosa Completa Máquina": {"P": 99, "M": 109, "G": 119},
        "Tosa Completa Tesoura": {"P": 129, "M": 149, "G": 169},
        "Tosa Higiênica": 25,
        "Hidratação": 29,
        "Escovação de Dente": 5,
        "Remoção de Subpelo": 25,
    },
    "Vila 11 Pinheiros": {
        "Banho": {"P": 64, "M": 84, "G": 104, "GG": 124},
        "Tosa Completa Máquina": {"P": 129, "M": 159, "G": 189},
        "Tosa Completa Tesoura": {"P": 169, "M": 189, "G": 229},
        "Tosa Higiênica": 25,
        "Hidratação": 39,
        "Escovação de Dente": 5,
        "Remoção de Subpelo": 35,
    },
    "Vila 11 Vila Mariana": {
        "Banho": {"P": 64, "M": 84, "G": 104, "GG": 124},
        "Tosa Completa Máquina": {"P": 129, "M": 159, "G": 189},
        "Tosa Completa Tesoura": {"P": 169, "M": 189, "G": 229},
        "Tosa Higiênica": 25,
        "Hidratação": 39,
        "Escovação de Dente": 5,
        "Remoção de Subpelo": 35,
    },
    "Ventana": {
        "Banho": {"P": 59, "M": 79, "G": 99, "GG": 119},
        "Tosa Completa Máquina": {"P": 129, "M": 149, "G": 179},
        "Tosa Completa Tesoura": {"P": 149, "M": 179, "G": 209},
        "Tosa Higiênica": 25,
        "Hidratação": 39,
        "Escovação de Dente": 5,
        "Remoção de Subpelo": 35,
        "SpaPet": 249,
    },
}


def preco_sugerido(condominio, servico, porte):
    """Retorna o preço de referência AVULSO (visita única), ou None se não achar."""
    tabela = PRECOS_REFERENCIA.get(condominio, {})
    valor = tabela.get(servico)
    if valor is None:
        return None
    if isinstance(valor, dict):
        return valor.get(porte)
    return valor


# Quando o serviço é vendido DENTRO de um pacote (várias visitas compradas
# de uma vez), o preço por visita sai com desconto em relação ao preço
# avulso (visita única) acima — o mesmo desconto de 10% que já está
# embutido na fórmula de "Saldo em valor" da planilha (coluna com
# L*F*0,9-I). Usamos esse mesmo fator aqui pra sugerir um valor de pacote
# coerente com o que a planilha já calcula sozinha.
DESCONTO_PACOTE = 0.90


def preco_sugerido_pacote(condominio, servico, porte):
    """Preço de referência POR VISITA dentro de um pacote (já com o desconto de pacote aplicado)."""
    preco_avulso = preco_sugerido(condominio, servico, porte)
    if preco_avulso is None:
        return None
    return round(preco_avulso * DESCONTO_PACOTE, 2)

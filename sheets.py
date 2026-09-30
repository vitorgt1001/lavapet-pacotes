"""
sheets.py
------------------------------------------------------------
Toda a comunicação com o "mundo de fora" do app fica concentrada aqui:
  - leitura da planilha Google Sheets (via gspread) — usada no Painel e
    no Histórico, sempre leitura direta, sem risco.
  - cadastro de um pacote novo (Novo Pacote) — escrita direta na
    planilha, também sem risco (é só um "adicionar linha").
  - registrar um atendimento (Registrar Atendimento) — NÃO escreve
    direto na planilha. Chama a API que você adicionou no Apps Script
    (API_Pacotes.gs), porque essa ação precisa acionar a mesma lógica
    de desconto de saldo + envio de WhatsApp + histórico que já existe
    lá. Fazer isso duplicado aqui no Python ia criar duas fontes de
    verdade pra regra de negócio — mais fácil desalinhar com o tempo.
"""

import os
import re
import pandas as pd
import gspread
import requests
import streamlit as st
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

ABA_PACOTES = "Pacotes_Clientes"
ABA_HISTORICO = "Historico_Pacotes"

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


def _tem_secrets_streamlit():
    """
    True quando o app está rodando na Streamlit Community Cloud (ou tem um
    .streamlit/secrets.toml local) e as credenciais foram configuradas lá
    em vez de no .env. Isso permite o MESMO código funcionar tanto local
    (com .env + arquivo .json) quanto hospedado (com Secrets da Streamlit
    Cloud) — sem precisar de dois app.py diferentes.
    """
    try:
        return hasattr(st, "secrets") and len(st.secrets) > 0
    except Exception:
        return False


def _config(chave, padrao=""):
    """Busca uma config primeiro nos Secrets da Streamlit, depois no .env local."""
    if _tem_secrets_streamlit() and chave in st.secrets:
        return st.secrets[chave]
    return os.environ.get(chave, padrao)


def _checar_config():
    faltando = []
    if not _config("SPREADSHEET_ID"):
        faltando.append("SPREADSHEET_ID")
    usando_secrets = _tem_secrets_streamlit() and "gcp_service_account" in st.secrets
    if not usando_secrets and not os.path.exists(_config("GOOGLE_SERVICE_ACCOUNT_FILE", "credenciais_google.json")):
        faltando.append("GOOGLE_SERVICE_ACCOUNT_FILE (arquivo .json não encontrado) ou [gcp_service_account] nos Secrets")
    if faltando:
        raise RuntimeError(
            "Configuração incompleta: " + ", ".join(faltando) +
            ". Veja o README.md."
        )


def _client():
    _checar_config()
    if _tem_secrets_streamlit() and "gcp_service_account" in st.secrets:
        creds = Credentials.from_service_account_info(dict(st.secrets["gcp_service_account"]), scopes=SCOPES)
    else:
        arquivo = _config("GOOGLE_SERVICE_ACCOUNT_FILE", "credenciais_google.json")
        creds = Credentials.from_service_account_file(arquivo, scopes=SCOPES)
    return gspread.authorize(creds)


def _abrir_planilha():
    return _client().open_by_key(_config("SPREADSHEET_ID"))


def _worksheet(nome_aba):
    return _abrir_planilha().worksheet(nome_aba)


def _dedup_headers(cabecalho):
    """
    Sua planilha tem cabeçalho repetido (ex: duas colunas 'Saldo' — uma de
    quantidade, outra de valor). Isso quebraria o get_all_records() do
    gspread (ele não aceita cabeçalho duplicado), então lemos os valores
    crus e renomeamos aqui: a 2ª ocorrência de 'Saldo' vira 'Saldo (2)',
    e assim por diante — só pra identificar a coluna, não mexe na
    planilha.
    """
    vistos = {}
    resultado = []
    for nome in cabecalho:
        chave = (nome or "").strip()
        if chave not in vistos:
            vistos[chave] = 1
            resultado.append(chave)
        else:
            vistos[chave] += 1
            resultado.append(f"{chave} ({vistos[chave]})")
    return resultado


def _ler_aba_df(nome_aba) -> pd.DataFrame:
    aba = _worksheet(nome_aba)
    valores = aba.get_all_values()
    if not valores:
        return pd.DataFrame()
    cabecalho = _dedup_headers(valores[0])
    return pd.DataFrame(valores[1:], columns=cabecalho)


def ler_pacotes_df() -> pd.DataFrame:
    """Lê a aba Pacotes_Clientes inteira como DataFrame (colunas = cabeçalho da planilha)."""
    return _ler_aba_df(ABA_PACOTES)


def ler_historico_df() -> pd.DataFrame:
    """Lê a aba Historico_Pacotes inteira como DataFrame."""
    return _ler_aba_df(ABA_HISTORICO)


def _mapear_valores_por_cabecalho(aba, valores_por_nome_coluna: dict):
    """
    Monta uma linha (lista) do tamanho do cabeçalho da aba, colocando cada
    valor na posição da coluna cujo texto do cabeçalho bate (ignorando
    maiúsculas/minúsculas e espaços nas pontas). Colunas que não aparecem
    em valores_por_nome_coluna ficam em branco.

    Isso evita depender de "a coluna X é a 5ª" — se um dia a ordem das
    colunas mudar na planilha, o app continua escrevendo no lugar certo
    desde que o TEXTO do cabeçalho não mude.
    """
    cabecalho = aba.row_values(1)
    linha = [""] * len(cabecalho)
    nomes_normalizados = {c.strip().lower(): i for i, c in enumerate(cabecalho)}

    nao_encontradas = []
    for nome, valor in valores_por_nome_coluna.items():
        chave = nome.strip().lower()
        if chave in nomes_normalizados:
            linha[nomes_normalizados[chave]] = valor
        else:
            nao_encontradas.append(nome)

    if nao_encontradas:
        raise RuntimeError(
            "Não encontrei estas colunas no cabeçalho da aba '" + aba.title + "': "
            + ", ".join(nao_encontradas)
            + ". Confira se o nome está escrito exatamente igual ao da planilha "
            "(edite CAMPOS_NOVO_PACOTE em catalogo.py ou sheets.py se precisar ajustar)."
        )
    return linha


def _herdar_formulas_da_linha_anterior(aba, numero_linha_nova):
    """
    Sua planilha calcula 'Saldo' (e outras colunas) com fórmula em cada
    linha (ex: =E2-F2). Quando o app adiciona uma linha nova por baixo
    dos panos (append_row), o Google Sheets NÃO copia fórmula nenhuma
    pra linha nova sozinho — só copia quando alguém arrasta manualmente
    pela interface. Sem isso, a linha nova ficaria com 'Saldo' em branco.

    Essa função corrige isso: olha a linha de dados anterior, pega toda
    fórmula que achar (célula começando com '='), e recria a mesma
    fórmula na linha nova, ajustando o número da linha.
    """
    numero_linha_anterior = numero_linha_nova - 1
    if numero_linha_anterior < 2:
        return  # linha nova é a primeira linha de dados, não tem o que herdar

    celulas = aba.get(f"{numero_linha_anterior}:{numero_linha_anterior}", value_render_option="FORMULA")
    if not celulas:
        return
    linha_formulas = celulas[0]

    atualizacoes = []
    for indice, conteudo in enumerate(linha_formulas):
        if isinstance(conteudo, str) and conteudo.startswith("="):
            nova_formula = re.sub(
                rf"(?<=[A-Za-z]){numero_linha_anterior}\b",
                str(numero_linha_nova),
                conteudo,
            )
            coluna_a1 = gspread.utils.rowcol_to_a1(numero_linha_nova, indice + 1)
            atualizacoes.append({"range": coluna_a1, "values": [[nova_formula]]})

    if atualizacoes:
        aba.batch_update(atualizacoes, value_input_option="USER_ENTERED")


def cadastrar_novo_pacote(dados: dict):
    """
    dados: dict com chaves = nome da coluna EXATAMENTE como está no
    cabeçalho da aba Pacotes_Clientes, ex:
        {"Telefone": "...", "Nome": "...", "Condomínio": "...",
         "Serviço": "...", "Qtd Comprada": 10, "Valor Pago": 590,
         "Data Compra": "2026-09-30"}

    Colunas de fórmula (como 'Saldo') não precisam vir nesse dict — são
    preenchidas automaticamente copiando a fórmula da linha anterior.
    """
    aba = _worksheet(ABA_PACOTES)
    linha = _mapear_valores_por_cabecalho(aba, dados)
    aba.append_row(linha, value_input_option="USER_ENTERED")
    numero_linha_nova = len(aba.get_all_values())
    _herdar_formulas_da_linha_anterior(aba, numero_linha_nova)


def chamar_api_apps_script(acao: str, **kwargs):
    """Chama o endpoint novo do Apps Script (API_Pacotes.gs)."""
    url = _config("APPS_SCRIPT_URL")
    token = _config("APPS_SCRIPT_TOKEN")
    if not url:
        raise RuntimeError("APPS_SCRIPT_URL não configurado. Veja o README.md.")
    if not token:
        raise RuntimeError("APPS_SCRIPT_TOKEN não configurado. Veja o README.md.")

    payload = {"acao": acao, "token": token}
    payload.update(kwargs)

    resposta = requests.post(url, json=payload, timeout=30)
    resposta.raise_for_status()
    dados = resposta.json()
    if not dados.get("ok"):
        raise RuntimeError("Erro retornado pelo Apps Script: " + str(dados.get("erro")))
    return dados


def registrar_atendimento(telefone, servico, condominio="", data_reconciliacao=""):
    return chamar_api_apps_script(
        "registrar_atendimento",
        telefone=telefone,
        servico=servico,
        condominio=condominio,
        dataReconciliacao=data_reconciliacao,
    )

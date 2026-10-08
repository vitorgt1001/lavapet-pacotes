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
    Sua planilha calcula 'Saldo' com fórmula em cada linha — a coluna G
    (saldo em quantidade: =E-F) e a coluna N (saldo em valor). Quando o
    app adiciona uma linha nova por baixo dos panos, o Google Sheets NÃO
    copia fórmula nenhuma pra linha nova sozinho — só copia quando
    alguém arrasta manualmente pela interface. Sem isso, a linha nova
    ficaria com 'Saldo' em branco.

    Em vez de tentar "procurar" uma linha de cima pra copiar (isso deu
    problema com a planilha tendo quase mil linhas em branco no meio),
    a gente já sabe exatamente qual é o formato dessas duas fórmulas
    (conferido direto na sua planilha, na linha da Luciana), então
    recria elas direto, só trocando o número da linha. Mais simples e
    não depende de "achar" uma linha de exemplo em lugar nenhum.

    Se um dia você mudar essas fórmulas na planilha (por exemplo, mudar
    o jeito que o 'Saldo' é calculado), me avisa que eu ajusto aqui
    também — do contrário, as linhas novas continuam usando este
    padrão.
    """
    l = numero_linha_nova
    formula_saldo_quantidade = f"=E{l}-F{l}"
    formula_saldo_valor = f'=SE(F{l}="";"";SE(F{l}=0;;L{l}*F{l}*0,9-I{l}))'

    aba.batch_update(
        [
            {"range": f"G{l}", "values": [[formula_saldo_quantidade]]},
            {"range": f"N{l}", "values": [[formula_saldo_valor]]},
        ],
        value_input_option="USER_ENTERED",
    )


def cadastrar_novo_pacote(dados: dict):
    """
    dados: dict com chaves = nome da coluna EXATAMENTE como está no
    cabeçalho da aba Pacotes_Clientes, ex:
        {"Telefone": "...", "Nome": "...", "Condomínio": "...",
         "Serviço": "...", "Qtd Comprada": 10, "Valor Pago": 590,
         "Data Compra": "2026-09-30"}

    Colunas de fórmula (como 'Saldo') não precisam vir nesse dict — são
    preenchidas automaticamente com a fórmula certa.
    """
    aba = _worksheet(ABA_PACOTES)
    linha = _mapear_valores_por_cabecalho(aba, dados)

    # NÃO usamos aba.append_row() aqui de propósito: como a planilha tem
    # centenas de linhas em branco com só uma caixinha marcada na coluna
    # "Marcar Atendimento", o Google Sheets tenta adivinhar sozinho onde
    # começa a "tabela" pra anexar a linha — e erra, grudando os dados a
    # partir dessa coluna em vez da A. Em vez disso, calculamos a próxima
    # linha vazia nós mesmos e escrevemos explicitamente a partir da
    # coluna A, sem chance de errar de coluna.
    #
    # E calculamos essa "próxima linha vazia" olhando só a coluna A
    # (Telefone) — não a linha inteira. Se olhássemos a linha inteira, a
    # gente ia cair lá embaixo, depois de todas aquelas centenas de
    # linhas de template (que têm a coluna A vazia, mas têm a caixinha
    # da coluna J marcada). Olhando só a coluna A, a linha nova cai bem
    # depois do seu último cliente real — sem aquele monte de linhas em
    # branco no meio.
    numero_linha_nova = len(aba.col_values(1)) + 1

    # A planilha tem um número fixo de linhas (o "tamanho da grade"). Se a
    # linha nova ultrapassar esse limite, adiciona mais linhas em branco
    # automaticamente antes de escrever, pra nunca dar erro de "exceeds
    # grid limits".
    if numero_linha_nova > aba.row_count:
        aba.add_rows(numero_linha_nova - aba.row_count + 500)

    aba.update(f"A{numero_linha_nova}", [linha], value_input_option="USER_ENTERED")
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


def finalizar_atendimento(telefone):
    """
    Dispara AGORA a mensagem de WhatsApp consolidada pro cliente, juntando
    todos os serviços registrados pra ele desde a última mensagem enviada.
    Usada pelo botão "Finalizar atendimento e enviar resumo" — em vez de
    mandar uma mensagem a cada serviço marcado em "Registrar Atendimento",
    os serviços ficam acumulados (no lado do Apps Script) até você clicar
    aqui, e aí sai uma mensagem só com tudo que o cliente usou na visita.
    """
    return chamar_api_apps_script("finalizar_atendimento", telefone=telefone)


def finalizar_visita_completa(telefone, condominio, servicos):
    """
    Fluxo novo: manda a lista INTEIRA de serviços de uma visita de uma vez
    só. Do lado do Apps Script, primeiro confere se tem saldo pra todos ANTES
    de gravar qualquer coisa na planilha — se faltar saldo pra algum, nada é
    gravado e vem um erro explicando qual. Se passar, grava tudo e manda UMA
    mensagem de WhatsApp com o resumo.

    Usada pelo botão "Finalizar atendimento e enviar resumo" no fluxo novo,
    onde nada toca na planilha enquanto você só vai marcando os serviços na
    tela — só quando você confirma aqui é que vira "realidade" na planilha.
    """
    return chamar_api_apps_script(
        "finalizar_visita_completa",
        telefone=telefone,
        condominio=condominio,
        servicos=servicos,
    )


def cancelar_atendimento_pendente(telefone):
    """
    Apaga a fila de serviços pendentes desse telefone (do lado do Apps
    Script) SEM mandar mensagem nenhuma pro cliente. Usada pelo botão
    "🧹 Cancelar o que ainda não enviei" — serve pra quando um teste deu
    errado: sem isso, o que sobrou do teste ficaria "esperando" e se
    juntaria sozinho com o próximo atendimento de verdade desse mesmo
    telefone (mesmo depois de você já ter corrigido a planilha na mão).
    """
    return chamar_api_apps_script("cancelar_atendimento_pendente", telefone=telefone)

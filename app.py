"""
app.py — LavaPet | Controle de Pacotes
------------------------------------------------------------
Pra rodar:  streamlit run app.py
(precisa ter configurado o .env antes — veja README.md)
"""

import datetime as dt
import os

import pandas as pd
import streamlit as st

import catalogo
import sheets

st.set_page_config(page_title="LavaPet — Controle de Pacotes", page_icon="🐾", layout="wide")


def _senha_configurada():
    try:
        if "APP_PASSWORD" in st.secrets:
            return st.secrets["APP_PASSWORD"]
    except Exception:
        pass
    return os.environ.get("APP_PASSWORD", "")


_SENHA = _senha_configurada()

# Só pede senha quando uma senha foi configurada (uso local, só seu, sem
# hospedar em lugar nenhum, continua funcionando sem pedir nada). Quando o
# app estiver hospedado na internet (Streamlit Cloud), configure
# APP_PASSWORD nos Secrets pra proteger o acesso.
if _SENHA:
    if "autenticado" not in st.session_state:
        st.session_state.autenticado = False

    if not st.session_state.autenticado:
        st.title("🐾 LavaPet — Controle de Pacotes")
        senha_digitada = st.text_input("Senha de acesso", type="password")
        if st.button("Entrar"):
            if senha_digitada == _SENHA:
                st.session_state.autenticado = True
                st.rerun()
            else:
                st.error("Senha incorreta.")
        st.stop()

st.sidebar.title("🐾 LavaPet")
pagina = st.sidebar.radio(
    "Menu",
    ["📊 Painel de Pacotes", "➕ Novo Pacote", "✅ Registrar Atendimento", "📜 Histórico do Cliente"],
)

st.sidebar.divider()
st.sidebar.caption("Controle de pacotes — versão simples, feita com Streamlit.")


def formatar_erro(e: Exception):
    st.error(f"Deu erro: {e}")


# ------------------------------------------------------------
# 📊 Painel de Pacotes
# ------------------------------------------------------------
if pagina == "📊 Painel de Pacotes":
    st.header("📊 Painel de Pacotes")

    try:
        df = sheets.ler_pacotes_df()
    except Exception as e:
        formatar_erro(e)
        st.stop()

    if df.empty:
        st.info("Nenhum pacote cadastrado ainda.")
        st.stop()

    col_qtd_comprada = next((c for c in df.columns if "qtd comprada" in c.lower()), None)
    col_qtd_usada = next((c for c in df.columns if "qtd usada" in c.lower()), None)
    col_condominio = next((c for c in df.columns if "condom" in c.lower()), None)
    col_servico = next((c for c in df.columns if "servi" in c.lower()), None)
    col_nome = next((c for c in df.columns if c.lower().strip() == "nome"), None)
    col_telefone = next((c for c in df.columns if "telefone" in c.lower()), None)

    if col_qtd_comprada and col_qtd_usada:
        df["Saldo"] = pd.to_numeric(df[col_qtd_comprada], errors="coerce").fillna(0) - pd.to_numeric(
            df[col_qtd_usada], errors="coerce"
        ).fillna(0)
    else:
        st.warning(
            "Não encontrei as colunas 'Qtd Comprada' / 'Qtd Usada' pra calcular o saldo — "
            "mostrando a tabela crua mesmo assim."
        )

    col1, col2, col3 = st.columns(3)
    col1.metric("Total de pacotes", len(df))
    if "Saldo" in df.columns:
        col2.metric("Pacotes com saldo > 0", int((df["Saldo"] > 0).sum()))
        col3.metric("Pacotes zerados", int((df["Saldo"] <= 0).sum()))

    st.divider()

    filtro_condominio = "Todos"
    if col_condominio:
        opcoes = ["Todos"] + sorted(df[col_condominio].dropna().unique().tolist())
        filtro_condominio = st.selectbox("Filtrar por condomínio", opcoes)

    apenas_com_saldo = st.checkbox("Mostrar só quem tem saldo disponível", value=True)

    df_filtrado = df.copy()
    if col_condominio and filtro_condominio != "Todos":
        df_filtrado = df_filtrado[df_filtrado[col_condominio] == filtro_condominio]
    if apenas_com_saldo and "Saldo" in df_filtrado.columns:
        df_filtrado = df_filtrado[df_filtrado["Saldo"] > 0]

    colunas_exibir = [c for c in [col_nome, col_telefone, col_condominio, col_servico, col_qtd_comprada, col_qtd_usada, "Saldo"] if c]
    st.dataframe(df_filtrado[colunas_exibir] if colunas_exibir else df_filtrado, use_container_width=True)


# ------------------------------------------------------------
# ➕ Novo Pacote
# ------------------------------------------------------------
elif pagina == "➕ Novo Pacote":
    st.header("➕ Cadastrar Pacote Novo")
    st.caption("Escreve direto na planilha (aba Pacotes_Clientes).")

    with st.form("form_novo_pacote"):
        c1, c2 = st.columns(2)
        with c1:
            nome = st.text_input("Nome do cliente")
            telefone = st.text_input("Telefone (com DDD)", placeholder="11999999999")
            condominio = st.selectbox("Condomínio", catalogo.CONDOMINIOS)
        with c2:
            servico = st.selectbox("Serviço", catalogo.SERVICOS)
            porte = st.selectbox("Porte (referência)", catalogo.PORTES)
            data_compra = st.date_input("Data da compra", value=dt.date.today())

        sugestao = catalogo.preco_sugerido(condominio, servico, porte)

        c3, c4 = st.columns(2)
        with c3:
            qtd_comprada = st.number_input("Quantidade comprada", min_value=1, step=1, value=10)
        with c4:
            valor_pago = st.number_input(
                "Valor total pago (R$)",
                min_value=0.0,
                step=1.0,
                value=float(sugestao * qtd_comprada) if sugestao else 0.0,
                help="Preenchido com sugestão baseada na tabela de preços × quantidade — ajuste se teve desconto.",
            )

        enviar = st.form_submit_button("Cadastrar pacote")

    if enviar:
        if not nome or not telefone:
            st.warning("Preencha pelo menos nome e telefone.")
        else:
            try:
                valor_unitario = round(valor_pago / qtd_comprada, 2) if qtd_comprada else 0
                sheets.cadastrar_novo_pacote({
                    "Nome": nome,
                    "Telefone": telefone,
                    "Condomínio": condominio,
                    "Serviço": servico,
                    "Qtd Comprada": int(qtd_comprada),
                    "Qtd Usada": 0,
                    "Valor Pago": valor_pago,
                    "Valor Unitário": valor_unitario,
                    "Data Compra": data_compra.strftime("%Y-%m-%d"),
                })
                st.success(f"Pacote de {nome} cadastrado! ({int(qtd_comprada)}x {servico} — {condominio})")
            except Exception as e:
                formatar_erro(e)
                st.info(
                    "Se o erro falar de coluna não encontrada, o nome do cabeçalho na planilha "
                    "é diferente do que o app está tentando usar — me chama que eu ajusto."
                )


# ------------------------------------------------------------
# ✅ Registrar Atendimento
# ------------------------------------------------------------
elif pagina == "✅ Registrar Atendimento":
    st.header("✅ Registrar Atendimento")
    st.caption(
        "Desconta 1 do saldo do pacote. Se marcar como retroativo, NÃO manda WhatsApp pro cliente "
        "(só atualiza o histórico) — igual ao comportamento da planilha hoje."
    )

    with st.form("form_atendimento"):
        c1, c2 = st.columns(2)
        with c1:
            telefone = st.text_input("Telefone do cliente (com DDD)", placeholder="11999999999")
            servico = st.selectbox("Serviço utilizado", catalogo.SERVICOS)
        with c2:
            condominio = st.selectbox("Condomínio (opcional, ajuda a desempatar)", [""] + catalogo.CONDOMINIOS)
            retroativo = st.checkbox("Lançamento retroativo (reconciliação)")

        data_reconciliacao = ""
        if retroativo:
            data_reconciliacao = st.date_input("Data em que o atendimento realmente aconteceu").strftime("%Y-%m-%d")

        enviar = st.form_submit_button("Registrar atendimento")

    if enviar:
        if not telefone:
            st.warning("Preencha o telefone do cliente.")
        else:
            try:
                resultado = sheets.registrar_atendimento(
                    telefone=telefone,
                    servico=servico,
                    condominio=condominio,
                    data_reconciliacao=data_reconciliacao,
                )
                if resultado.get("mensagemEnviada"):
                    st.success(f"Atendimento registrado! Saldo restante: {resultado.get('saldoRestante')}. WhatsApp enviado ao cliente.")
                else:
                    st.success(f"Atendimento retroativo registrado! Saldo restante: {resultado.get('saldoRestante')}. Nenhuma mensagem foi enviada.")
            except Exception as e:
                formatar_erro(e)


# ------------------------------------------------------------
# 📜 Histórico do Cliente
# ------------------------------------------------------------
elif pagina == "📜 Histórico do Cliente":
    st.header("📜 Histórico do Cliente")

    telefone_busca = st.text_input("Buscar por telefone (com DDD)", placeholder="11999999999")

    try:
        df = sheets.ler_historico_df()
    except Exception as e:
        formatar_erro(e)
        st.stop()

    if df.empty:
        st.info("Nenhum histórico registrado ainda.")
        st.stop()

    col_telefone = next((c for c in df.columns if "telefone" in c.lower()), None)

    if telefone_busca and col_telefone:
        digitos_busca = "".join(ch for ch in telefone_busca if ch.isdigit())
        df_filtrado = df[df[col_telefone].astype(str).str.replace(r"\D", "", regex=True).str.contains(digitos_busca)]
    else:
        df_filtrado = df

    st.dataframe(df_filtrado, use_container_width=True)
    st.caption(f"{len(df_filtrado)} registro(s).")

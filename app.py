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
    col_pedido = next((c for c in df.columns if "pedido" in c.lower()), None)

    # Sua planilha tem várias linhas em branco pré-formatadas lá embaixo
    # (com fórmula de saldo mas sem cliente nenhum) — não contam como pacote.
    # Usa o Nome (mais confiável que o Telefone, que às vezes fica vazio).
    if col_nome:
        df = df[df[col_nome].astype(str).str.strip() != ""]

    if df.empty:
        st.info("Nenhum pacote cadastrado ainda.")
        st.stop()

    if col_qtd_comprada and col_qtd_usada:
        df["Saldo"] = pd.to_numeric(df[col_qtd_comprada], errors="coerce").fillna(0) - pd.to_numeric(
            df[col_qtd_usada], errors="coerce"
        ).fillna(0)
    else:
        st.warning(
            "Não encontrei as colunas 'Qtd Comprada' / 'Qtd Usada' pra calcular o saldo — "
            "mostrando a tabela crua mesmo assim."
        )

    # Uma COMPRA pode virar várias linhas aqui (ex: banho + dente + tosa
    # comprados juntos = 3 linhas, uma por serviço). Pra contar "pacotes"
    # de um jeito que bate com a realidade (compras, não linhas), agrupa
    # pelo "ID do Pedido" quando ele existir — linhas com o mesmo ID do
    # Pedido são a MESMA compra e contam como 1 só. Linha sem ID do
    # Pedido (pacotes antigos, de antes dessa coluna existir, ou
    # cadastrados avulsos) continua contando cada uma por si.
    if col_pedido:
        pedido_vazio = df[col_pedido].astype(str).str.strip() == ""
        grupo = df[col_pedido].astype(str).where(~pedido_vazio, df.index.astype(str) + "__avulso")
    else:
        grupo = df.index.astype(str)

    total_pacotes = grupo.nunique()
    if "Saldo" in df.columns:
        ativo_por_grupo = df.groupby(grupo)["Saldo"].apply(lambda s: (s > 0).any())
        pacotes_com_saldo = int(ativo_por_grupo.sum())
        pacotes_zerados = int((~ativo_por_grupo).sum())
    else:
        pacotes_com_saldo = pacotes_zerados = None

    col1, col2, col3 = st.columns(3)
    col1.metric("Total de pacotes", total_pacotes)
    if pacotes_com_saldo is not None:
        col2.metric("Pacotes com saldo > 0", pacotes_com_saldo)
        col3.metric("Pacotes zerados", pacotes_zerados)
    st.caption(
        "\"Pacote\" aqui = uma compra (pode juntar banho + dente + tosa, por exemplo). "
        "\"Com saldo > 0\" conta um pacote como ativo se QUALQUER serviço dele ainda tiver saldo."
    )

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

    colunas_exibir = [c for c in [col_nome, col_telefone, col_condominio, col_servico, col_qtd_comprada, col_qtd_usada, "Saldo", col_pedido] if c]
    st.dataframe(df_filtrado[colunas_exibir] if colunas_exibir else df_filtrado, use_container_width=True)


# ------------------------------------------------------------
# ➕ Novo Pacote
# ------------------------------------------------------------
elif pagina == "➕ Novo Pacote":
    st.header("➕ Cadastrar Pacote Novo")
    st.caption(
        "Escreve direto na planilha (aba Pacotes_Clientes). Se a compra incluir mais de um "
        "serviço (ex: banho + dente + tosa junto), marca todos abaixo — cada um vira uma linha "
        "na planilha, mas todas ficam ligadas pelo mesmo \"ID do Pedido\", contando como 1 pacote só "
        "no Painel."
    )

    c1, c2 = st.columns(2)
    with c1:
        nome = st.text_input("Nome do cliente")
        telefone = st.text_input("Telefone (com DDD)", placeholder="11999999999")
        condominio = st.selectbox("Condomínio", catalogo.CONDOMINIOS)
    with c2:
        servicos_selecionados = st.multiselect(
            "Serviço(s) incluídos nessa compra", catalogo.SERVICOS, default=["Banho"]
        )
        porte = st.selectbox("Porte (referência, usado pro preço do Banho)", catalogo.PORTES)
        data_compra = st.date_input("Data da compra", value=dt.date.today())

    st.divider()
    st.caption("Quantidade comprada de cada serviço (normalmente é igual pra todos — ajuste se for diferente, ex: só 1 tosa):")

    qtd_padrao = st.number_input("Quantidade padrão", min_value=1, step=1, value=4)

    quantidades = {}
    if servicos_selecionados:
        colunas_qtd = st.columns(len(servicos_selecionados))
        for col, servico in zip(colunas_qtd, servicos_selecionados):
            with col:
                quantidades[servico] = col.number_input(
                    servico, min_value=0, step=1, value=int(qtd_padrao), key=f"qtd_{servico}"
                )

    soma_sugestao = sum(
        (catalogo.preco_sugerido(condominio, s, porte) or 0) * quantidades.get(s, 0)
        for s in servicos_selecionados
    )
    valor_pago = st.number_input(
        "Valor total pago (R$) — a soma de tudo que o cliente pagou nessa compra",
        min_value=0.0,
        step=1.0,
        value=float(soma_sugestao) if soma_sugestao else 0.0,
        help="Preenchido com sugestão baseada na tabela de preços — ajuste se teve desconto.",
    )

    enviar = st.button("Cadastrar pacote")

    if enviar:
        if not nome or not telefone:
            st.warning("Preencha pelo menos nome e telefone.")
        elif not servicos_selecionados:
            st.warning("Marca pelo menos 1 serviço.")
        else:
            servicos_validos = [s for s in servicos_selecionados if quantidades.get(s, 0) > 0]
            if not servicos_validos:
                st.warning("A quantidade de todos os serviços marcados está em 0.")
            else:
                id_pedido = f"PED-{dt.datetime.now():%Y%m%d%H%M%S}"
                erros = []
                cadastrados = []
                for i, servico in enumerate(servicos_validos):
                    qtd = int(quantidades[servico])
                    # o valor pago (total da compra) fica só na primeira linha do
                    # pedido, pra não contar o mesmo dinheiro várias vezes se
                    # alguém somar a coluna Valor Pago depois.
                    valor_pago_linha = valor_pago if i == 0 else 0
                    valor_unitario = round(valor_pago_linha / qtd, 2) if (i == 0 and qtd) else 0
                    try:
                        sheets.cadastrar_novo_pacote({
                            "Nome": nome,
                            "Telefone": telefone,
                            "Condomínio": condominio,
                            "Serviço": servico,
                            "Qtd Comprada": qtd,
                            "Qtd Usada": 0,
                            "Valor Pago": valor_pago_linha,
                            "Valor Unitário": valor_unitario,
                            "Data Compra": data_compra.strftime("%Y-%m-%d"),
                            "ID do Pedido": id_pedido,
                        })
                        cadastrados.append(f"{qtd}x {servico}")
                    except Exception as e:
                        erros.append(f"{servico}: {e}")

                if cadastrados:
                    st.success(f"Pacote de {nome} cadastrado! ({' + '.join(cadastrados)} — {condominio}). ID do Pedido: {id_pedido}")
                if erros:
                    for msg in erros:
                        formatar_erro(Exception(msg))
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

"""
app.py — LavaPet | Controle de Pacotes
------------------------------------------------------------
Pra rodar:  streamlit run app.py
(precisa ter configurado o .env antes — veja README.md)
"""

import datetime as dt
import os
import re

import pandas as pd
import streamlit as st

import catalogo
import sheets


# Caminho da logo — fica direto na raiz do repositório (mesmo lugar do
# app.py), sem precisar de pasta separada. Se o arquivo não estiver
# presente no servidor por algum motivo, o app usa a pata de cachorro 🐾
# no lugar em vez de travar com erro — assim uma logo faltando nunca
# derruba o app inteiro.
LOGO_PATH = "logo_lavapet.png"
_TEM_LOGO = os.path.exists(LOGO_PATH)

st.set_page_config(
    page_title="LavaPet — Controle de Pacotes",
    page_icon=LOGO_PATH if _TEM_LOGO else "🐾",
    layout="wide",
)


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
        if _TEM_LOGO:
            st.image(LOGO_PATH, width=120)
            st.title("LavaPet — Controle de Pacotes")
        else:
            st.title("🐾 LavaPet — Controle de Pacotes")
        senha_digitada = st.text_input("Senha de acesso", type="password")
        if st.button("Entrar"):
            if senha_digitada == _SENHA:
                st.session_state.autenticado = True
                st.rerun()
            else:
                st.error("Senha incorreta.")
        st.stop()

if _TEM_LOGO:
    st.sidebar.image(LOGO_PATH, width=120)
else:
    st.sidebar.title("🐾 LavaPet")
pagina = st.sidebar.radio(
    "Menu",
    ["📊 Painel de Pacotes", "➕ Novo Pacote", "✅ Registrar Atendimento", "📜 Histórico do Cliente"],
)

st.sidebar.divider()
st.sidebar.caption("Controle de pacotes — versão simples, feita com Streamlit.")


def formatar_erro(e: Exception):
    st.error(f"Deu erro: {e}")


def _condominio_canonico(valor: str):
    """
    Tenta casar o texto de condomínio que veio da planilha (que pode ter
    vindo de copia/cola, com espaço a mais, caractere invisível de zero
    largura, ou maiúscula/minúscula diferente) com um dos nomes EXATOS
    esperados pelo app (catalogo.CONDOMINIOS). Sem isso, o
    autopreenchimento do campo Condomínio simplesmente não acontecia
    (sem nenhum erro visível) pra qualquer linha com uma dessas pequenas
    diferenças de texto — foi o que aconteceu com uma linha do Leandro em
    21/10/2026.

    Devolve o nome "oficial" (com a grafia certinha do catalogo.py) se
    achar uma correspondência, ou None se não achar nada parecido.
    """
    if not valor:
        return None
    limpo = re.sub(r"[​‌‍﻿\xa0]", " ", str(valor))
    limpo = re.sub(r"\s+", " ", limpo).strip().lower()
    if not limpo:
        return None
    for opcao in catalogo.CONDOMINIOS:
        if re.sub(r"\s+", " ", opcao).strip().lower() == limpo:
            return opcao
    return None


def _data_br(data_iso: str) -> str:
    """Converte 'YYYY-MM-DD' pra 'DD/MM/YYYY', só pra mostrar na tela."""
    try:
        return dt.datetime.strptime(data_iso, "%Y-%m-%d").strftime("%d/%m/%Y")
    except Exception:
        return data_iso or ""


def _normalizar_servico_para_comparacao(valor: str) -> str:
    """
    Mesma ideia da normalizarServico_ do Apps Script: tira o PORTE do final
    (ex: "Banho P" -> "banho"), se tiver, porque pacotes antigos (cadastrados
    na mão antes desse app existir) guardam o serviço com o porte junto,
    mas o menu "Serviço utilizado" só oferece o nome genérico. Usada só
    pro aviso rápido de saldo aqui no Python — quem decide de verdade
    sempre é o Apps Script, que já faz essa mesma normalização.
    """
    texto = re.sub(r"\s+(GG|P|M|G)$", "", str(valor or "").strip(), flags=re.IGNORECASE)
    return texto.strip().lower()


def _mensagem_erro_amigavel(servico: str, e: Exception) -> str:
    """
    Mesma lógica de antes pra detectar 'sem saldo' e dar uma mensagem mais
    clara — só que agora reaproveitada pra cada item de uma lista (lançamento
    retroativo em lote), não só pra um clique avulso.
    """
    mensagem_erro = str(e).lower()
    if "saldo" in mensagem_erro and ("dispon" in mensagem_erro or "zerad" in mensagem_erro or "nenhum pacote" in mensagem_erro):
        return f"{servico}: sem saldo disponível nesse pacote (confere se precisa comprar um pacote novo)"
    return f"{servico}: {e}"


@st.cache_data(ttl=60)
def _buscar_cliente_por_telefone(digitos: str):
    """
    Procura esse telefone nos pacotes já cadastrados e devolve o nome e
    condomínio da última compra encontrada — usado tanto em "Novo Pacote"
    (pra não digitar os dados do cliente de novo) quanto em "Registrar
    Atendimento" (pra preencher o Condomínio sozinho). Guarda o resultado
    por 60s (cache) pra não ficar lendo a planilha a cada letra digitada.
    """
    try:
        df = sheets.ler_pacotes_df()
    except Exception:
        return None
    col_telefone = next((c for c in df.columns if "telefone" in c.lower()), None)
    col_nome = next((c for c in df.columns if c.lower().strip() == "nome"), None)
    col_condominio = next((c for c in df.columns if "condom" in c.lower()), None)
    if not col_telefone or not col_nome:
        return None
    digitos_coluna = df[col_telefone].astype(str).str.replace(r"\D", "", regex=True)
    encontrados = df[digitos_coluna == digitos]
    if encontrados.empty:
        return None
    ultima = encontrados.iloc[-1]
    return {
        "nome": str(ultima.get(col_nome, "")).strip(),
        "condominio": str(ultima.get(col_condominio, "")).strip() if col_condominio else "",
    }


def _saldo_disponivel_cliente(digitos_tel, servico, condominio):
    """
    Confere, direto na planilha, quanto de saldo esse cliente tem agora pra
    esse serviço — usada só pra avisar NA HORA em "Registrar Atendimento" se
    provavelmente não vai ter saldo suficiente, sem gravar nada (a gravação
    de verdade só acontece quando você clica em "Finalizar", que confere o
    saldo de novo do lado do Apps Script antes de escrever qualquer coisa).

    Devolve None quando não dá pra conferir agora (planilha fora do ar, por
    exemplo) — nesse caso o app deixa passar sem avisar, e quem decide de
    verdade é sempre o "Finalizar".
    """
    try:
        df = sheets.ler_pacotes_df()
    except Exception:
        return None
    col_telefone = next((c for c in df.columns if "telefone" in c.lower()), None)
    col_servico = next((c for c in df.columns if c.lower().strip() == "serviço" or c.lower().strip() == "servico"), None)
    col_condominio = next((c for c in df.columns if "condom" in c.lower()), None)
    col_qtd_comprada = next((c for c in df.columns if "qtd comprada" in c.lower()), None)
    col_qtd_usada = next((c for c in df.columns if "qtd usada" in c.lower()), None)
    if not all([col_telefone, col_servico, col_qtd_comprada, col_qtd_usada]):
        return None

    digitos_coluna = df[col_telefone].astype(str).str.replace(r"\D", "", regex=True)
    filtro = (digitos_coluna == digitos_tel) & (
        df[col_servico].astype(str).apply(_normalizar_servico_para_comparacao)
        == _normalizar_servico_para_comparacao(servico)
    )
    if condominio and col_condominio:
        filtro &= df[col_condominio].astype(str).str.strip().str.lower() == str(condominio).strip().lower()

    linhas = df[filtro]
    if linhas.empty:
        return 0

    comprada = pd.to_numeric(linhas[col_qtd_comprada], errors="coerce").fillna(0)
    usada = pd.to_numeric(linhas[col_qtd_usada], errors="coerce").fillna(0)
    saldo = (comprada - usada).clip(lower=0).sum()
    return int(saldo)


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
    col_nome_pet = next((c for c in df.columns if "nome do pet" in c.lower()), None)

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

    # Limpa a busca ANTES de desenhar o campo (mesma regra do Streamlit já
    # usada em "Registrar Atendimento" — não dá pra mudar o valor de um
    # widget com key definida DEPOIS que ele já foi desenhado na tela
    # nessa mesma rodada).
    if st.session_state.get("_painel_limpar_busca"):
        st.session_state["painel_busca"] = ""
        st.session_state["_painel_limpar_busca"] = False

    col_busca, col_limpar_busca = st.columns([4, 1])
    with col_busca:
        busca = st.text_input(
            "🔎 Buscar por nome, telefone ou nome do pet",
            placeholder="Ex: Maria, 11999999999 ou Rex",
            key="painel_busca",
        )
    with col_limpar_busca:
        st.write("")
        st.write("")
        if st.button("🧹 Limpar busca", disabled=not busca):
            st.session_state["_painel_limpar_busca"] = True
            st.rerun()

    filtro_condominio = "Todos"
    if col_condominio:
        opcoes = ["Todos"] + sorted(df[col_condominio].dropna().unique().tolist())
        filtro_condominio = st.selectbox("Filtrar por condomínio", opcoes)

    apenas_com_saldo = st.checkbox("Mostrar só quem tem saldo disponível", value=True)

    df_filtrado = df.copy()
    if busca:
        termo = busca.strip().lower()
        mascara = pd.Series(False, index=df_filtrado.index)
        if col_nome:
            mascara |= df_filtrado[col_nome].astype(str).str.lower().str.contains(termo, na=False, regex=False)
        if col_telefone:
            mascara |= df_filtrado[col_telefone].astype(str).str.lower().str.contains(termo, na=False, regex=False)
        if col_nome_pet:
            mascara |= df_filtrado[col_nome_pet].astype(str).str.lower().str.contains(termo, na=False, regex=False)
        df_filtrado = df_filtrado[mascara]
    if col_condominio and filtro_condominio != "Todos":
        df_filtrado = df_filtrado[df_filtrado[col_condominio] == filtro_condominio]
    if apenas_com_saldo and "Saldo" in df_filtrado.columns:
        df_filtrado = df_filtrado[df_filtrado["Saldo"] > 0]

    if busca and df_filtrado.empty:
        st.info(f"Nenhum resultado pra \"{busca}\".")

    colunas_exibir = [c for c in [col_nome, col_nome_pet, col_telefone, col_condominio, col_servico, col_qtd_comprada, col_qtd_usada, "Saldo", col_pedido] if c]
    st.dataframe(df_filtrado[colunas_exibir] if colunas_exibir else df_filtrado, use_container_width=True)


# ------------------------------------------------------------
# ➕ Novo Pacote
# ------------------------------------------------------------
elif pagina == "➕ Novo Pacote":
    st.header("➕ Cadastrar Pacote Novo")
    st.caption(
        "Uma compra pode juntar mais de um serviço (ex: Banho + Tosa Higiênica "
        "no mesmo pedido). Marca abaixo tudo que fez parte dessa compra — cada "
        "serviço vira uma linha na planilha, mas todas ficam ligadas pelo mesmo "
        "ID do Pedido, e o Painel conta a compra toda como 1 pacote só."
    )

    # Os campos abaixo ficam FORA de um st.form de propósito: a lista de
    # serviços marcados no multiselect muda a quantidade de campos de
    # quantidade que aparecem na tela (um por serviço), e isso só atualiza
    # na hora se o campo não estiver dentro de um st.form.

    # Lê o telefone já digitado (se houver) ANTES de desenhar os campos na
    # tela — assim dá pra fazer a busca e preparar o auto-preenchimento do
    # Nome sem precisar colocar o campo Telefone antes do campo Nome (o
    # campo Nome volta a aparecer PRIMEIRO, do jeito que você já tava
    # acostumado — só trocar a ordem na tela da última vez claramente
    # confundiu e fez telefone e nome serem digitados no campo errado).
    telefone_digitado = st.session_state.get("np_telefone", "")
    digitos_tel = "".join(ch for ch in telefone_digitado if ch.isdigit())
    cliente_existente = _buscar_cliente_por_telefone(digitos_tel) if len(digitos_tel) >= 8 else None

    # Só preenche nome/condomínio sozinho na PRIMEIRA vez que reconhece
    # esse telefone — depois disso, se você editar o nome ou o condomínio
    # na mão, o app não fica sobrescrevendo de novo a cada tecla.
    #
    # IMPORTANTE: só sobrescreve o Nome se o cadastro antigo encontrado TEM
    # um nome preenchido. Sem isso, se esse telefone já tiver uma linha
    # antiga na planilha com o Nome em branco (ex: linha de teste), o app
    # apagava sozinho o nome que você tinha acabado de digitar, assim que
    # terminava de digitar o telefone — por isso às vezes parecia que
    # "sumia" o nome mesmo com o campo visualmente preenchido antes.
    if cliente_existente and st.session_state.get("_np_tel_autofill") != digitos_tel:
        if cliente_existente["nome"]:
            st.session_state["np_nome"] = cliente_existente["nome"]
        condominio_canonico = _condominio_canonico(cliente_existente["condominio"])
        if condominio_canonico:
            st.session_state["np_condominio"] = condominio_canonico
        st.session_state["_np_tel_autofill"] = digitos_tel

    c1, c2 = st.columns(2)
    with c1:
        nome = st.text_input("Nome do cliente", key="np_nome")
        telefone = st.text_input(
            "Telefone (com DDD)", placeholder="11999999999", key="np_telefone"
        )
        condominio = st.selectbox("Condomínio", catalogo.CONDOMINIOS, key="np_condominio")
    with c2:
        data_compra = st.date_input("Data da compra", value=dt.date.today())

    if cliente_existente:
        extra = f" — {cliente_existente['condominio']}" if cliente_existente["condominio"] else ""
        st.success(
            f"Cliente já cadastrado: **{cliente_existente['nome']}**{extra} "
            "(preenchi nome e condomínio acima, pode ajustar se precisar)."
        )
    elif len(digitos_tel) >= 8:
        st.caption("Não achei esse telefone em pacotes anteriores — cliente novo.")

    servicos_escolhidos = st.multiselect(
        "Quais serviços fazem parte dessa compra?",
        catalogo.SERVICOS,
        default=["Banho"],
    )

    st.divider()

    quantidades = {}
    sugestoes = {}
    nomes_pet = {}
    portes_por_servico = {}
    if servicos_escolhidos:
        st.caption(
            "Quantidade comprada de cada serviço. Pra serviços com preço por porte (Banho, "
            "Tosa Completa Máquina/Tesoura), escolhe o porte do pet aqui também — é o que vai "
            "ser gravado junto do nome do serviço na planilha (ex: \"Banho P\"), pra diferenciar "
            "certinho de um \"Banho M\" do mesmo cliente. E, se quiser, o nome do pet — útil "
            "quando o cliente tem mais de um pacote pro mesmo serviço, ex: Banho P pra um "
            "cachorro e Banho M pra outro:"
        )
        colunas = st.columns(len(servicos_escolhidos))
        for col, servico in zip(colunas, servicos_escolhidos):
            with col:
                quantidades[servico] = col.number_input(
                    servico, min_value=1, step=1, value=4, key=f"qtd_{servico}"
                )
                # Só pede porte pra serviços cujo preço realmente muda por
                # porte (catalogo.servico_varia_por_porte) — pra serviços
                # de preço fixo (ex: Tosa Higiênica), gravar um porte
                # junto do nome não faria sentido nenhum.
                if catalogo.servico_varia_por_porte(servico):
                    portes_por_servico[servico] = col.selectbox(
                        "Porte deste serviço",
                        catalogo.PORTES,
                        key=f"porte_{servico}",
                    )
                else:
                    portes_por_servico[servico] = None
                nomes_pet[servico] = col.text_input(
                    "Nome do pet (opcional)", key=f"pet_{servico}", placeholder="Ex: Bart"
                )
                # Sugestão já com os 10% de desconto de pacote (preço
                # avulso só pra visita única — comprando o pacote fechado
                # sai mais barato por visita, igual já é calculado na
                # planilha). Usa o porte escolhido ACIMA, pra esse
                # serviço especificamente (None pra serviço de preço fixo,
                # que não usa porte pra nada).
                porte_deste_servico = portes_por_servico[servico]
                sugestao_unit = catalogo.preco_sugerido_pacote(condominio, servico, porte_deste_servico) or 0
                sugestoes[servico] = round(sugestao_unit * quantidades[servico], 2)
                col.caption(f"Sugestão (c/ 10% de pacote): R$ {sugestoes[servico]:.2f}")
    else:
        st.info("Marca pelo menos um serviço acima.")

    soma_sugerida = sum(sugestoes.values()) if sugestoes else 0.0

    valor_pago_total = st.number_input(
        "Valor total pago nessa compra (R$)",
        min_value=0.0,
        step=1.0,
        value=float(soma_sugerida),
        help="Preenchido com a soma das sugestões acima — ajuste se teve desconto ou valor diferente.",
    )

    def _calcular_alocacao(servicos, quantidades, sugestoes, soma_sugerida, valor_pago_total, portes_por_servico):
        """
        Divide o valor total pago entre os serviços da compra, na mesma
        proporção da sugestão de preço de cada um (ex: se Banho sugeriu
        R$316 e Tosa sugeriu R$100, de um total de R$400 pagos, Banho
        "leva" 76% e Tosa 24%). Devolve uma linha de detalhe por serviço —
        é a mesma conta usada tanto pra mostrar a memória de cálculo na
        tela quanto pra gravar na planilha, então o que você vê aqui é
        exatamente o que vai ser salvo.

        O campo "Serviço" de cada linha já sai com o porte junto quando
        aplicável (ex: "Banho P") — é esse texto que vai pra coluna
        Serviço da planilha, e é ele que permite diferenciar dois pacotes
        do mesmo cliente pro mesmo serviço genérico (ex: Banho P x Banho
        M) na hora de registrar atendimento depois.
        """
        peso_total = soma_sugerida if soma_sugerida > 0 else sum(quantidades.values())
        linhas = []
        for servico in servicos:
            qtd = int(quantidades[servico])
            porte_servico = portes_por_servico.get(servico)
            preco_avulso = catalogo.preco_sugerido(condominio, servico, porte_servico) or 0
            preco_c_desconto = catalogo.preco_sugerido_pacote(condominio, servico, porte_servico) or 0
            if soma_sugerida > 0:
                peso = sugestoes[servico] / peso_total
            else:
                peso = (qtd / peso_total) if peso_total else 0
            valor_pago_servico = round(valor_pago_total * peso, 2)
            valor_unitario = round(valor_pago_servico / qtd, 2) if qtd else 0
            servico_rotulo = f"{servico} {porte_servico}" if porte_servico else servico
            linhas.append({
                "Serviço": servico_rotulo,
                "_servico_generico": servico,
                "Qtd": qtd,
                "Preço avulso (un.)": preco_avulso,
                "Preço c/ desconto (un.)": preco_c_desconto,
                "% do total pago": round(peso * 100, 1),
                "Valor pago (alocado)": valor_pago_servico,
                "Valor unitário final": valor_unitario,
            })
        return linhas

    alocacao = (
        _calcular_alocacao(servicos_escolhidos, quantidades, sugestoes, soma_sugerida, valor_pago_total, portes_por_servico)
        if servicos_escolhidos
        else []
    )

    if alocacao:
        st.caption("📋 Memória de cálculo — é isso que vai ser gravado na planilha:")
        df_memoria = pd.DataFrame(alocacao)
        colunas_memoria = [
            "Serviço", "Qtd", "Preço avulso (un.)", "Preço c/ desconto (un.)",
            "% do total pago", "Valor pago (alocado)", "Valor unitário final",
        ]
        st.dataframe(
            df_memoria[colunas_memoria].style.format({
                "Preço avulso (un.)": "R$ {:.2f}",
                "Preço c/ desconto (un.)": "R$ {:.2f}",
                "% do total pago": "{:.1f}%",
                "Valor pago (alocado)": "R$ {:.2f}",
                "Valor unitário final": "R$ {:.2f}",
            }),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(f"Total pago: R$ {sum(l['Valor pago (alocado)'] for l in alocacao):.2f}")

    enviar = st.button("Cadastrar pacote", type="primary")

    if enviar:
        digitos_tel_final = "".join(ch for ch in telefone if ch.isdigit())
        # Trava de segurança pra pegar nome/telefone trocados de campo antes
        # de gravar na planilha (já aconteceu um teste onde isso foi
        # digitado no campo errado e foi direto pra planilha sem avisar).
        if not nome or not telefone:
            st.warning(
                "Preencha pelo menos nome e telefone. Se usou o preenchimento automático "
                "do navegador, clica dentro do campo e digita algo (ou apaga e digita de "
                "novo) antes de cadastrar."
            )
        elif len(digitos_tel_final) < 10 or len(digitos_tel_final) > 11:
            st.warning(
                f"O telefone \"{telefone}\" não parece certo (achei {len(digitos_tel_final)} "
                "número(s), o esperado é 10 ou 11 com DDD). Confere se não trocou com o campo Nome."
            )
        elif nome.strip().replace(" ", "").isdigit():
            st.warning(
                f"O campo Nome está só com números (\"{nome}\") — confere se não trocou com o "
                "campo Telefone."
            )
        elif not servicos_escolhidos:
            st.warning("Marca pelo menos um serviço.")
        else:
            try:
                # Todo pacote ganha um "ID do Pedido" compartilhado entre os
                # serviços dessa mesma compra — é isso que deixa o Painel
                # contar "Banho + Tosa comprados juntos" como 1 pacote só,
                # em vez de 2.
                id_pedido = f"PED-{dt.datetime.now():%Y%m%d%H%M%S}"

                for linha in alocacao:
                    servico_generico = linha["_servico_generico"]
                    servico = linha["Serviço"]
                    qtd = linha["Qtd"]
                    valor_pago_servico = linha["Valor pago (alocado)"]
                    valor_unitario = linha["Valor unitário final"]
                    sheets.cadastrar_novo_pacote({
                        "Nome": nome,
                        "Telefone": telefone,
                        "Condomínio": condominio,
                        "Serviço": servico,
                        "Nome do Pet": nomes_pet.get(servico_generico, "").strip(),
                        "Qtd Comprada": qtd,
                        "Qtd Usada": 0,
                        "Valor Pago": valor_pago_servico,
                        "Valor Unitário": valor_unitario,
                        "Data Compra": data_compra.strftime("%Y-%m-%d"),
                        "ID do Pedido": id_pedido,
                    })
                resumo = ", ".join(f"{int(quantidades[s])}x {s}" for s in servicos_escolhidos)
                st.success(f"Pacote de {nome} cadastrado! ({resumo} — {condominio})")
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
        "Nada é gravado na planilha enquanto você só vai marcando os serviços aqui — eles "
        "ficam guardados só nesta tela, numa lista que você pode revisar e corrigir antes de "
        "confirmar. Registrar e mandar mensagem agora são SEMPRE duas coisas separadas, tanto "
        "faz se é de hoje ou retroativo: \"Registrar atendimento\" (ou \"Finalizar lançamento "
        "retroativo\") grava os itens marcados e desconta o saldo — isso nunca manda mensagem "
        "sozinho. Quem manda é só o botão \"Enviar resumo pro cliente\", lá embaixo, e só "
        "quando VOCÊ clicar nele — pode ser na hora, mais tarde, no dia seguinte, ou nunca (se "
        "for um lançamento retroativo que o cliente não precisa ficar sabendo, por exemplo, é "
        "só não clicar). Se desistir no meio ou marcar algo errado, é só cancelar — como nada "
        "foi gravado ainda, não sobra nada pra corrigir na planilha depois."
    )

    # Mensagem de sucesso (verde) e de aviso (amarelo) da ação anterior
    # (guardadas antes de limpar a tela — ver comentário mais abaixo, nos
    # blocos "if enviar" / "if finalizar" / "if finalizar_retro").
    if st.session_state.get("_ra_sucesso_msg"):
        st.success(st.session_state.pop("_ra_sucesso_msg"))
    if st.session_state.get("_ra_aviso_msg"):
        st.warning(st.session_state.pop("_ra_aviso_msg"))

    # Limpa os campos ANTES de criar os widgets (igual o Streamlit exige —
    # não dá pra mudar st.session_state de um campo DEPOIS que ele já foi
    # desenhado na tela nessa mesma rodada, só dá erro "cannot be modified
    # after the widget...". Por isso a limpeza acontece aqui em cima, numa
    # rodada seguinte, marcada pela flag "_ra_limpar" lá no final do envio).
    # Só limpamos a tela depois de FINALIZAR (ou cancelar) a visita, ou
    # lançar um retroativo — marcar um serviço avulso NÃO limpa mais o
    # telefone, porque normalmente você vai marcar mais de um serviço
    # seguido pro mesmo cliente antes de finalizar a visita.
    if st.session_state.get("_ra_limpar"):
        st.session_state["ra_telefone"] = ""
        st.session_state["ra_condominio"] = ""
        st.session_state.pop("_ra_tel_autofill", None)
        st.session_state["_ra_limpar"] = False

    # Fora de st.form de propósito (igual na página "Novo Pacote"): dentro
    # de um st.form, NENHUM campo atualiza a tela até você clicar no botão
    # final — então o Condomínio nunca preenchia sozinho, e a caixinha de
    # data retroativa só "aparecia" no exato instante em que você clicava
    # em Registrar, tarde demais pra você escolher a data certa (ela usava
    # a data de hoje sem avisar). Tirando do form, os dois já atualizam na
    # hora.
    telefone_digitado = st.session_state.get("ra_telefone", "")
    digitos_tel = "".join(ch for ch in telefone_digitado if ch.isdigit())
    cliente_existente = _buscar_cliente_por_telefone(digitos_tel) if len(digitos_tel) >= 8 else None

    if cliente_existente and st.session_state.get("_ra_tel_autofill") != digitos_tel:
        condominio_canonico = _condominio_canonico(cliente_existente["condominio"])
        if condominio_canonico:
            st.session_state["ra_condominio"] = condominio_canonico
        st.session_state["_ra_tel_autofill"] = digitos_tel

    c1, c2 = st.columns(2)
    with c1:
        telefone = st.text_input(
            "Telefone do cliente (com DDD)", placeholder="11999999999", key="ra_telefone"
        )
        servico = st.selectbox("Serviço utilizado", catalogo.SERVICOS)
    with c2:
        condominio = st.selectbox(
            "Condomínio (opcional, ajuda a desempatar)", [""] + catalogo.CONDOMINIOS, key="ra_condominio"
        )
        retroativo = st.checkbox("Lançamento retroativo (reconciliação)")

    if cliente_existente:
        extra = f" — {cliente_existente['condominio']}" if cliente_existente["condominio"] else ""
        st.success(f"Cliente encontrado: **{cliente_existente['nome']}**{extra} (confere se é o mesmo).")
    elif len(digitos_tel) >= 8:
        st.caption("Não achei esse telefone em pacotes anteriores.")

    data_reconciliacao = ""
    if retroativo:
        data_reconciliacao = st.date_input("Data em que o atendimento realmente aconteceu").strftime("%Y-%m-%d")

    # Duas listas guardadas só nesta tela (sessão do navegador) — NADA
    # disso foi gravado na planilha ainda. São por telefone, porque você
    # pode estar alternando entre clientes diferentes na mesma sessão.
    #
    # "_ra_pendentes": serviços de HOJE (fluxo normal) — ao finalizar,
    # grava tudo e manda UMA mensagem consolidada pro cliente.
    #
    # "_ra_pendentes_retro": serviços RETROATIVOS (correção de visita
    # passada) — cada item guarda também a própria data, porque dá pra
    # marcar itens de datas diferentes antes de finalizar. Ao finalizar,
    # grava cada um (com a data dele) e NUNCA manda mensagem — igual
    # sempre foi, só que agora dá pra revisar a lista antes de confirmar,
    # em vez de gravar na hora a cada clique.
    pendentes_por_telefone = st.session_state.setdefault("_ra_pendentes", {})
    pendentes_deste_cliente = pendentes_por_telefone.get(digitos_tel, [])

    pendentes_retro_por_telefone = st.session_state.setdefault("_ra_pendentes_retro", {})
    pendentes_retro_deste_cliente = pendentes_retro_por_telefone.get(digitos_tel, [])

    # Desambiguação: quando o cliente tem mais de um pacote compatível com
    # o serviço escolhido (ex: "Banho P" pro Bart e "Banho M" pro Romeu),
    # guardamos aqui a escolha pendente (por telefone) até você confirmar
    # qual pacote específico é esse atendimento — NADA é marcado na lista
    # de pendentes enquanto essa escolha não for confirmada.
    desambiguacao_por_telefone = st.session_state.setdefault("_ra_desambiguar", {})
    desambiguacao_pendente = desambiguacao_por_telefone.get(digitos_tel)

    if pendentes_deste_cliente:
        # Lista e "remover item" ficam dentro do MESMO quadro (container com
        # borda), pra ficar visualmente claro que uma coisa pertence à
        # outra — antes a lista tinha caixinha azul (st.info) e o "remover"
        # ficava solto embaixo, sem parecer parte do mesmo bloco.
        with st.container(border=True):
            st.markdown(
                "📋 **Itens marcados nesta visita (hoje)** (ainda **não** gravei na planilha "
                "nem mandei mensagem):"
            )
            st.markdown("\n".join(f"{i + 1}. {s}" for i, s in enumerate(pendentes_deste_cliente)))
            # Sem st.divider() aqui de propósito: em algumas versões do
            # Streamlit, a linha divisória "escapa" visualmente do quadro
            # com borda e dá a impressão de que virou uma caixa separada.
            # Um espaço em branco simples é mais seguro.
            st.write("")
            col_remover_sel, col_remover_botao = st.columns([2, 1])
            with col_remover_sel:
                indice_remover = st.selectbox(
                    "Marcou algo errado? Escolhe o item pra remover da lista",
                    options=list(range(len(pendentes_deste_cliente))),
                    format_func=lambda i: f"{i + 1}. {pendentes_deste_cliente[i]}",
                    key="ra_remover_indice",
                    label_visibility="visible",
                )
            with col_remover_botao:
                st.write("")
                st.write("")
                if st.button("Remover esse item"):
                    pendentes_deste_cliente.pop(indice_remover)
                    if not pendentes_deste_cliente:
                        pendentes_por_telefone.pop(digitos_tel, None)
                    st.rerun()

    if pendentes_retro_deste_cliente:
        with st.container(border=True):
            st.markdown(
                "🕒 **Itens retroativos marcados nesta visita** (ainda **não** gravei na "
                "planilha — finalizar NÃO manda mensagem sozinho; se quiser avisar o cliente "
                "desse lançamento, use o botão \"Enviar resumo pro cliente\" depois, é opcional):"
            )
            st.markdown(
                "\n".join(
                    f"{i + 1}. {item['servico']} — {item['data_br']}"
                    for i, item in enumerate(pendentes_retro_deste_cliente)
                )
            )
            st.write("")
            col_remover_sel_r, col_remover_botao_r = st.columns([2, 1])
            with col_remover_sel_r:
                indice_remover_r = st.selectbox(
                    "Marcou algo errado? Escolhe o item pra remover da lista",
                    options=list(range(len(pendentes_retro_deste_cliente))),
                    format_func=lambda i: (
                        f"{i + 1}. {pendentes_retro_deste_cliente[i]['servico']} — "
                        f"{pendentes_retro_deste_cliente[i]['data_br']}"
                    ),
                    key="ra_remover_indice_retro",
                    label_visibility="visible",
                )
            with col_remover_botao_r:
                st.write("")
                st.write("")
                if st.button("Remover esse item retroativo"):
                    pendentes_retro_deste_cliente.pop(indice_remover_r)
                    if not pendentes_retro_deste_cliente:
                        pendentes_retro_por_telefone.pop(digitos_tel, None)
                    st.rerun()

    # Quadro de desambiguação: aparece só quando o clique em "Marcar
    # serviço" (mais abaixo) encontrou mais de um pacote candidato pra
    # esse telefone + serviço. Enquanto estiver aberto, pede pra você
    # escolher o pacote certo (porte + nome do pet, se tiver, + saldo)
    # antes de marcar o item de verdade.
    if desambiguacao_pendente:
        with st.container(border=True):
            st.markdown(
                f"⚠️ **Esse cliente tem mais de um pacote pra \"{desambiguacao_pendente['servico']}\" "
                "— qual deles é esse atendimento?**"
            )
            candidatos = desambiguacao_pendente["candidatos"]

            def _rotulo_candidato(i):
                c = candidatos[i]
                partes = [c["servico"]]
                if c.get("nomePet"):
                    partes.append(f"pet: {c['nomePet']}")
                if c.get("condominio"):
                    partes.append(c["condominio"])
                partes.append(f"saldo: {c['saldo']}")
                return " — ".join(partes)

            indice_escolhido = st.radio(
                "Pacotes disponíveis",
                options=list(range(len(candidatos))),
                format_func=_rotulo_candidato,
                key="ra_desambiguar_escolha",
            )
            col_confirmar, col_cancelar_desamb = st.columns(2)
            with col_confirmar:
                confirmar_desambiguacao = st.button("✅ Confirmar escolha", type="primary")
            with col_cancelar_desamb:
                cancelar_desambiguacao = st.button("Cancelar escolha")

            if confirmar_desambiguacao:
                candidato = candidatos[indice_escolhido]
                servico_exato = candidato["servico"]
                if desambiguacao_pendente["retroativo"]:
                    pendentes_retro_por_telefone.setdefault(digitos_tel, []).append({
                        "servico": servico_exato,
                        "data": desambiguacao_pendente["data_reconciliacao"],
                        "data_br": _data_br(desambiguacao_pendente["data_reconciliacao"]),
                    })
                    st.session_state["_ra_sucesso_msg"] = (
                        f"\"{servico_exato}\" marcado como retroativo "
                        f"({_data_br(desambiguacao_pendente['data_reconciliacao'])}) — ainda não gravei "
                        "nada na planilha."
                    )
                else:
                    pendentes_por_telefone.setdefault(digitos_tel, []).append(servico_exato)
                    st.session_state["_ra_sucesso_msg"] = (
                        f"\"{servico_exato}\" marcado nesta visita — ainda não gravei nada na planilha."
                    )
                desambiguacao_por_telefone.pop(digitos_tel, None)
                st.rerun()

            if cancelar_desambiguacao:
                desambiguacao_por_telefone.pop(digitos_tel, None)
                st.rerun()

    rotulo_botao_marcar = "Marcar serviço retroativo nesta visita" if retroativo else "Marcar serviço nesta visita"
    enviar = st.button(
        rotulo_botao_marcar,
        type="primary",
        disabled=bool(desambiguacao_pendente),
        help=(
            "Resolva a escolha de pacote acima antes de marcar outro serviço." if desambiguacao_pendente else None
        ),
    )
    finalizar = st.button(
        "✅ Registrar atendimento (sem enviar mensagem)",
        disabled=not telefone or not pendentes_deste_cliente,
        help=(
            "Grava os itens marcados acima na planilha e desconta o saldo agora. NÃO manda "
            "nenhuma mensagem pro cliente — pra isso, use o botão \"Enviar resumo pro "
            "cliente\" logo abaixo, na hora que você quiser (agora, daqui a pouco, ou só "
            "amanhã de manhã)."
        ),
    )
    finalizar_retro = st.button(
        "🕒 Finalizar lançamento retroativo (sem mensagem)",
        disabled=not telefone or not pendentes_retro_deste_cliente,
    )

    st.divider()
    st.markdown("**📨 Enviar resumo pro cliente**")
    st.caption(
        "Manda UMA mensagem pro cliente com tudo que foi registrado (hoje ou retroativo, tanto "
        "faz) pra esse telefone desde a última mensagem enviada. Não precisa ser na mesma hora "
        "que você registrou — pode clicar aqui mais tarde, no dia seguinte, ou nunca clicar (se "
        "o cliente não precisa ficar sabendo). Se não tiver nada pendente de envio, o app avisa "
        "e não manda nada."
    )
    col_ver, col_enviar = st.columns(2)
    with col_ver:
        ver_resumo = st.button("👀 Ver resumo antes de enviar", disabled=not telefone)
    with col_enviar:
        enviar_resumo = st.button("📨 Enviar resumo pro cliente agora", disabled=not telefone)

    # Guarda o texto visualizado por telefone, pra continuar mostrando na
    # tela mesmo depois do rerun que o botão "Ver resumo" dispara (sem
    # isso, a prévia desaparecia assim que você olhava pra ela).
    resumo_visualizado_por_telefone = st.session_state.setdefault("_ra_resumo_visualizado", {})
    # Mesma ideia, mas pro caso de NÃO ter nada pendente: antes esse aviso só
    # aparecia lá em cima da página (longe do botão "Ver resumo"), então
    # parecia que o clique não tinha feito nada. Agora mostra bem aqui,
    # do lado do botão.
    resumo_vazio_por_telefone = st.session_state.setdefault("_ra_resumo_vazio", {})
    if digitos_tel in resumo_visualizado_por_telefone:
        with st.container(border=True):
            st.markdown("**Prévia da mensagem que será enviada:**")
            st.text(resumo_visualizado_por_telefone[digitos_tel])
    elif digitos_tel in resumo_vazio_por_telefone:
        st.info(
            "🔎 " + resumo_vazio_por_telefone[digitos_tel]
            + " (ou seja: não tem nada registrado pra esse telefone esperando envio — "
            "registre algum atendimento primeiro, ou é porque o último resumo já foi "
            "enviado)."
        )

    # Cancelar agora é simples e sem risco: como nada foi gravado na
    # planilha enquanto você só marca os serviços aqui (nem os
    # retroativos, que agora também só ficam na lista até o "Finalizar
    # lançamento retroativo"), cancelar é só esquecer as duas listas
    # desta tela — não precisa desfazer nada em lugar nenhum. Isso NÃO
    # mexe no que já foi registrado de verdade (e está esperando o
    # "Enviar resumo") — só limpa o que ainda estava marcado aqui na
    # tela, sem ter gravado nada.
    st.divider()
    cancelar_pendente = st.button(
        "🧹 Cancelar os itens marcados nesta visita (hoje e retroativos)",
        disabled=not pendentes_deste_cliente and not pendentes_retro_deste_cliente,
        help=(
            "Esquece as duas listas marcadas acima pra esse telefone. Como nada foi gravado "
            "na planilha ainda, não tem nada pra desfazer — só limpa a tela."
        ),
    )

    if enviar:
        if not telefone:
            st.warning("Preencha o telefone do cliente.")
        else:
            # Antes de marcar o item, confere se tem mais de um pacote
            # candidato pra esse telefone + serviço (ex: "Banho P" pro Bart
            # e "Banho M" pro Romeu). Se tiver só 0 ou 1, marca igual sempre
            # foi; se tiver 2+, abre o quadro de escolha acima em vez de
            # marcar na hora. Se a chamada falhar por qualquer motivo (ex:
            # Apps Script fora do ar), não bloqueia o fluxo — cai no
            # comportamento de sempre, e quem decide de verdade continua
            # sendo o "Finalizar".
            candidatos = []
            try:
                resposta_candidatos = sheets.listar_candidatos_pacote(telefone, servico, condominio)
                candidatos = resposta_candidatos.get("candidatos", [])
            except Exception:
                candidatos = []

            if len(candidatos) >= 2:
                desambiguacao_por_telefone[digitos_tel] = {
                    "servico": servico,
                    "candidatos": candidatos,
                    "retroativo": retroativo,
                    "data_reconciliacao": data_reconciliacao,
                }
                st.rerun()
            elif retroativo:
                # Só marca aqui na tela (igual o fluxo normal) — nada é gravado
                # na planilha ainda. Cada item guarda a PRÓPRIA data escolhida,
                # então dá pra marcar serviços de datas retroativas diferentes
                # antes de finalizar tudo de uma vez.
                pendentes_retro_por_telefone.setdefault(digitos_tel, []).append(
                    {"servico": servico, "data": data_reconciliacao, "data_br": _data_br(data_reconciliacao)}
                )
                st.session_state["_ra_sucesso_msg"] = (
                    f"\"{servico}\" marcado como retroativo ({_data_br(data_reconciliacao)}) — ainda não "
                    "gravei nada na planilha. Clica em \"Finalizar lançamento retroativo\" quando "
                    "terminar de marcar tudo dessa visita passada."
                )
                st.rerun()
            else:
                # Fluxo normal (não retroativo): NÃO grava nada na planilha
                # ainda — só marca aqui na tela. A conferência de saldo abaixo é
                # só um AVISO rápido (lê a planilha, mas não escreve nada); quem
                # decide de verdade é o "Finalizar", que confere tudo de novo
                # antes de gravar qualquer coisa.
                ja_marcados_mesmo_servico = sum(1 for s in pendentes_deste_cliente if s == servico)
                saldo_real = _saldo_disponivel_cliente(digitos_tel, servico, condominio)
                if saldo_real is not None and (saldo_real - ja_marcados_mesmo_servico) <= 0:
                    st.warning(
                        f"Esse cliente não parece ter mais saldo disponível pra \"{servico}\" "
                        "(considerando o que já tá marcado nesta visita). Confere se ele não "
                        "precisa de um pacote novo — ainda assim marquei o item na lista; o "
                        "\"Finalizar\" confere de novo e, se realmente não tiver saldo, nada é "
                        "gravado e ele te avisa."
                    )
                pendentes_por_telefone.setdefault(digitos_tel, []).append(servico)
                st.session_state["_ra_sucesso_msg"] = (
                    f"\"{servico}\" marcado nesta visita — ainda não gravei nada na planilha. "
                    "Clica em \"Finalizar atendimento\" quando terminar de marcar tudo que o "
                    "cliente usou."
                )
                st.rerun()

    if finalizar:
        # Grava cada item da lista, um de cada vez (igual o lançamento
        # retroativo faz) — e NÃO manda mensagem nenhuma: cada item
        # registrado entra na fila de pendências do Apps Script, e só sai
        # de lá quando você clicar em "Enviar resumo pro cliente", na
        # hora que você quiser. Item que der erro (ex: sem saldo) fica na
        # lista pra você corrigir e tentar de novo; os que derem certo
        # saem da lista.
        sucesso = []
        falhas = []
        restantes = []
        for servico_item in list(pendentes_deste_cliente):
            try:
                sheets.registrar_atendimento(
                    telefone=telefone,
                    servico=servico_item,
                    condominio=condominio,
                    data_reconciliacao="",
                )
                sucesso.append(servico_item)
            except Exception as e:
                falhas.append(_mensagem_erro_amigavel(servico_item, e))
                restantes.append(servico_item)

        if restantes:
            pendentes_por_telefone[digitos_tel] = restantes
        else:
            pendentes_por_telefone.pop(digitos_tel, None)

        if sucesso:
            # O que estava sendo mostrado na prévia (se tinha) ficou
            # desatualizado assim que novos itens entraram na fila — tira
            # da tela até você clicar em "Ver resumo" de novo.
            resumo_visualizado_por_telefone.pop(digitos_tel, None)
            resumo_vazio_por_telefone.pop(digitos_tel, None)

        if sucesso and not falhas:
            st.session_state["_ra_sucesso_msg"] = (
                "Registrado na planilha: " + ", ".join(sucesso) + ". Nenhuma mensagem foi "
                "enviada ainda — use \"Enviar resumo pro cliente\" quando quiser."
            )
            st.session_state["_ra_limpar"] = True
        else:
            if sucesso:
                st.session_state["_ra_sucesso_msg"] = "Registrado: " + ", ".join(sucesso) + "."
            st.session_state["_ra_aviso_msg"] = (
                "Não deu pra registrar (continuam marcados pra você corrigir e tentar de novo): "
                + "; ".join(falhas)
            )
        st.rerun()

    if ver_resumo:
        try:
            resultado = sheets.visualizar_resumo_pendente(telefone)
            if resultado.get("temPendente"):
                resumo_visualizado_por_telefone[digitos_tel] = resultado.get("mensagem", "")
                resumo_vazio_por_telefone.pop(digitos_tel, None)
            else:
                resumo_visualizado_por_telefone.pop(digitos_tel, None)
                resumo_vazio_por_telefone[digitos_tel] = (
                    resultado.get("motivo") or "Não tinha nada pendente de envio pra esse telefone."
                )
            st.rerun()
        except Exception as e:
            formatar_erro(e)

    if enviar_resumo:
        try:
            resultado = sheets.finalizar_atendimento(telefone)
            resumo_visualizado_por_telefone.pop(digitos_tel, None)
            resumo_vazio_por_telefone.pop(digitos_tel, None)
            if resultado.get("enviado"):
                servicos_enviados = resultado.get("servicos") or []
                msg = (
                    "Resumo enviado pro cliente! Serviços dessa mensagem: "
                    + ", ".join(servicos_enviados) + "."
                )
            else:
                msg = resultado.get("motivo") or "Não tinha nada pendente de envio pra esse telefone."
            st.session_state["_ra_sucesso_msg"] = msg
            st.rerun()
        except Exception as e:
            formatar_erro(e)

    if finalizar_retro:
        # Grava cada item da lista retroativa, um de cada vez (cada um com
        # a própria data) — NUNCA manda mensagem pro cliente, igual sempre
        # foi. Item que der erro (ex: sem saldo) fica na lista pra você
        # corrigir (ex: cadastrar um pacote novo) e tentar de novo; os que
        # derem certo saem da lista.
        sucesso = []
        falhas = []
        restantes = []
        for item in list(pendentes_retro_deste_cliente):
            try:
                sheets.registrar_atendimento(
                    telefone=telefone,
                    servico=item["servico"],
                    condominio=condominio,
                    data_reconciliacao=item["data"],
                )
                sucesso.append(f"{item['servico']} ({item['data_br']})")
            except Exception as e:
                falhas.append(_mensagem_erro_amigavel(item["servico"], e))
                restantes.append(item)

        if restantes:
            pendentes_retro_por_telefone[digitos_tel] = restantes
        else:
            pendentes_retro_por_telefone.pop(digitos_tel, None)

        if sucesso:
            # Também entraram na fila de pendências pro "Enviar resumo pro
            # cliente" — se tinha uma prévia antiga na tela, não vale mais.
            resumo_visualizado_por_telefone.pop(digitos_tel, None)
            resumo_vazio_por_telefone.pop(digitos_tel, None)

        if sucesso and not falhas:
            st.session_state["_ra_sucesso_msg"] = (
                "Lançamentos retroativos gravados: " + ", ".join(sucesso) + ". Nenhuma "
                "mensagem foi enviada — se quiser avisar o cliente, use \"Enviar resumo pro "
                "cliente\" quando quiser (é opcional)."
            )
            st.session_state["_ra_limpar"] = True
        else:
            if sucesso:
                st.session_state["_ra_sucesso_msg"] = "Gravado: " + ", ".join(sucesso) + "."
            st.session_state["_ra_aviso_msg"] = (
                "Não deu pra gravar (continuam marcados pra você corrigir e tentar de novo): "
                + "; ".join(falhas)
            )
        st.rerun()

    if cancelar_pendente:
        pendentes_por_telefone.pop(digitos_tel, None)
        pendentes_retro_por_telefone.pop(digitos_tel, None)
        desambiguacao_por_telefone.pop(digitos_tel, None)
        st.session_state["_ra_sucesso_msg"] = (
            "Cancelado — como nada tinha sido gravado na planilha, não sobrou nada pra desfazer."
        )
        st.session_state["_ra_limpar"] = True
        st.rerun()


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

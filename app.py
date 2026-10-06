"""
app.py — LavaPet | Controle de Pacotes
------------------------------------------------------------
Pra rodar:  streamlit run app.py
(precisa ter configurado o .env antes — veja README.md)
"""

import datetime as dt
import os
import time

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
        if cliente_existente["condominio"] in catalogo.CONDOMINIOS:
            st.session_state["np_condominio"] = cliente_existente["condominio"]
        st.session_state["_np_tel_autofill"] = digitos_tel

    c1, c2 = st.columns(2)
    with c1:
        nome = st.text_input("Nome do cliente", key="np_nome")
        telefone = st.text_input(
            "Telefone (com DDD)", placeholder="11999999999", key="np_telefone"
        )
        condominio = st.selectbox("Condomínio", catalogo.CONDOMINIOS, key="np_condominio")
    with c2:
        porte = st.selectbox("Porte (referência, pra sugestão de preço)", catalogo.PORTES)
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
    if servicos_escolhidos:
        st.caption("Quantidade comprada de cada serviço:")
        colunas = st.columns(len(servicos_escolhidos))
        for col, servico in zip(colunas, servicos_escolhidos):
            with col:
                quantidades[servico] = col.number_input(
                    servico, min_value=1, step=1, value=4, key=f"qtd_{servico}"
                )
                # Sugestão já com os 10% de desconto de pacote (preço
                # avulso só pra visita única — comprando o pacote fechado
                # sai mais barato por visita, igual já é calculado na
                # planilha).
                sugestao_unit = catalogo.preco_sugerido_pacote(condominio, servico, porte) or 0
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

    def _calcular_alocacao(servicos, quantidades, sugestoes, soma_sugerida, valor_pago_total):
        """
        Divide o valor total pago entre os serviços da compra, na mesma
        proporção da sugestão de preço de cada um (ex: se Banho sugeriu
        R$316 e Tosa sugeriu R$100, de um total de R$400 pagos, Banho
        "leva" 76% e Tosa 24%). Devolve uma linha de detalhe por serviço —
        é a mesma conta usada tanto pra mostrar a memória de cálculo na
        tela quanto pra gravar na planilha, então o que você vê aqui é
        exatamente o que vai ser salvo.
        """
        peso_total = soma_sugerida if soma_sugerida > 0 else sum(quantidades.values())
        linhas = []
        for servico in servicos:
            qtd = int(quantidades[servico])
            preco_avulso = catalogo.preco_sugerido(condominio, servico, porte) or 0
            preco_c_desconto = catalogo.preco_sugerido_pacote(condominio, servico, porte) or 0
            if soma_sugerida > 0:
                peso = sugestoes[servico] / peso_total
            else:
                peso = (qtd / peso_total) if peso_total else 0
            valor_pago_servico = round(valor_pago_total * peso, 2)
            valor_unitario = round(valor_pago_servico / qtd, 2) if qtd else 0
            linhas.append({
                "Serviço": servico,
                "Qtd": qtd,
                "Preço avulso (un.)": preco_avulso,
                "Preço c/ desconto (un.)": preco_c_desconto,
                "% do total pago": round(peso * 100, 1),
                "Valor pago (alocado)": valor_pago_servico,
                "Valor unitário final": valor_unitario,
            })
        return linhas

    alocacao = (
        _calcular_alocacao(servicos_escolhidos, quantidades, sugestoes, soma_sugerida, valor_pago_total)
        if servicos_escolhidos
        else []
    )

    if alocacao:
        st.caption("📋 Memória de cálculo — é isso que vai ser gravado na planilha:")
        df_memoria = pd.DataFrame(alocacao)
        st.dataframe(
            df_memoria.style.format({
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
                "Preencha pelo menos nome e telefone. "
                f"(O que o app recebeu: nome=\"{nome}\", telefone=\"{telefone}\" — "
                "se algum dos dois tiver vindo vazio mesmo você tendo digitado, me manda "
                "um print desse aviso, que agora ele mostra o que o app enxergou.)"
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
                    servico = linha["Serviço"]
                    qtd = linha["Qtd"]
                    valor_pago_servico = linha["Valor pago (alocado)"]
                    valor_unitario = linha["Valor unitário final"]
                    sheets.cadastrar_novo_pacote({
                        "Nome": nome,
                        "Telefone": telefone,
                        "Condomínio": condominio,
                        "Serviço": servico,
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
        "Desconta 1 do saldo do pacote. Se marcar como retroativo, NÃO manda WhatsApp pro cliente "
        "(só atualiza o histórico) — igual ao comportamento da planilha hoje."
    )

    # Mensagem de sucesso do envio anterior (guardada antes de limpar a tela
    # — ver comentário mais abaixo, no bloco "if enviar").
    if st.session_state.get("_ra_sucesso_msg"):
        st.success(st.session_state.pop("_ra_sucesso_msg"))

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
        if cliente_existente["condominio"] in catalogo.CONDOMINIOS:
            st.session_state["ra_condominio"] = cliente_existente["condominio"]
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

    enviar = st.button("Registrar atendimento", type="primary")

    if enviar:
        if not telefone:
            st.warning("Preencha o telefone do cliente.")
        else:
            # Trava contra clique duplo: se clicar duas vezes rápido (ou a
            # página demorar pra responder e der outro clique por engano),
            # sem isso o app registrava o MESMO atendimento duas vezes,
            # descontando 2 do saldo em vez de 1. Só deixa repetir o mesmo
            # telefone+serviço de novo depois de alguns segundos.
            assinatura = (digitos_tel, servico, condominio, retroativo, data_reconciliacao)
            agora_ts = time.time()
            ultimo = st.session_state.get("_ra_ultimo_envio")
            if ultimo and ultimo[0] == assinatura and (agora_ts - ultimo[1]) < 8:
                st.warning(
                    "Esse mesmo atendimento acabou de ser registrado agora mesmo — não registrei de "
                    "novo pra não descontar em dobro. Se for outro atendimento de verdade, espera "
                    "alguns segundos e clica de novo."
                )
            else:
                st.session_state["_ra_ultimo_envio"] = (assinatura, agora_ts)
                try:
                    resultado = sheets.registrar_atendimento(
                        telefone=telefone,
                        servico=servico,
                        condominio=condominio,
                        data_reconciliacao=data_reconciliacao,
                    )
                    if resultado.get("mensagemEnviada"):
                        msg = (
                            f"Atendimento registrado! Saldo restante: {resultado.get('saldoRestante')}. "
                            "WhatsApp enviado ao cliente."
                        )
                    else:
                        msg = (
                            f"Atendimento retroativo registrado! Saldo restante: {resultado.get('saldoRestante')}. "
                            "Nenhuma mensagem foi enviada."
                        )
                    # Guarda a mensagem de sucesso pra mostrar DEPOIS de limpar a
                    # tela (ela é lida lá em cima, no início da página, na
                    # próxima vez que a tela desenhar) e limpa os campos —
                    # assim a tela já fica em branco, pronta pro próximo
                    # atendimento, em vez de ficar com o telefone anterior.
                    st.session_state["_ra_sucesso_msg"] = msg
                    st.session_state["ra_telefone"] = ""
                    st.session_state["ra_condominio"] = ""
                    st.session_state.pop("_ra_tel_autofill", None)
                    st.rerun()
                except Exception as e:
                    mensagem_erro = str(e).lower()
                    if "saldo" in mensagem_erro and ("dispon" in mensagem_erro or "zerad" in mensagem_erro or "nenhum pacote" in mensagem_erro):
                        st.warning(
                            f"Esse cliente não tem mais saldo disponível para \"{servico}\" nesse "
                            "pacote. Confere se ele já usou tudo e precisa comprar um pacote novo."
                        )
                    else:
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

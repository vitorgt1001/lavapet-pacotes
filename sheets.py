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
        "Desconta 1 do saldo do pacote a cada serviço marcado. A mensagem de WhatsApp pro "
        "cliente NÃO sai a cada item — ela fica \"guardada\" e só é enviada (uma vez só, com "
        "tudo que foi usado) quando você clicar em \"Finalizar atendimento e enviar resumo\", "
        "lá embaixo. Lançamento retroativo nunca manda mensagem, igual já era antes."
    )

    # Mensagem de sucesso da ação anterior (guardada antes de limpar a tela
    # — ver comentário mais abaixo, no bloco "if enviar" / "if finalizar").
    if st.session_state.get("_ra_sucesso_msg"):
        st.success(st.session_state.pop("_ra_sucesso_msg"))

    # Limpa os campos ANTES de criar os widgets (igual o Streamlit exige —
    # não dá pra mudar st.session_state de um campo DEPOIS que ele já foi
    # desenhado na tela nessa mesma rodada, só dá erro "cannot be modified
    # after the widget...". Por isso a limpeza acontece aqui em cima, numa
    # rodada seguinte, marcada pela flag "_ra_limpar" lá no final do envio).
    # Só limpamos a tela depois de FINALIZAR o atendimento (ou lançar um
    # retroativo) — registrar um serviço avulso NÃO limpa mais o telefone,
    # porque normalmente você vai marcar mais de um serviço seguido pro
    # mesmo cliente antes de finalizar a visita.
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

    # Lista local (só pra mostrar na tela) dos serviços já marcados nesta
    # visita, pra você acompanhar o que já foi registrado antes de clicar
    # em "Finalizar atendimento". É por telefone, porque você pode estar
    # alternando entre clientes diferentes na mesma sessão do app.
    pendentes_por_telefone = st.session_state.setdefault("_ra_pendentes", {})
    pendentes_deste_cliente = pendentes_por_telefone.get(digitos_tel, [])

    if pendentes_deste_cliente:
        st.info(
            "📋 Itens registrados nesta visita (ainda **não** enviei a mensagem pro cliente):\n\n"
            + "\n".join(f"- {s}" for s in pendentes_deste_cliente)
        )
        # Essa lista é só uma "nota" guardada aqui na tela do navegador —
        # ela NÃO lê a planilha nem o que está guardado do lado do Apps
        # Script. Se você editar a planilha na mão (apagar/corrigir linhas
        # de teste, por exemplo), essa lista aqui não sabe disso e continua
        # mostrando o que tinha antes. Esse botão só limpa essa nota na
        # tela — não apaga nem desfaz nada na planilha nem no WhatsApp.
        if st.button("🗑️ Limpar essa lista (só a nota na tela, não afeta a planilha)"):
            pendentes_por_telefone.pop(digitos_tel, None)
            st.rerun()

    enviar = st.button("Registrar atendimento", type="primary")
    finalizar = st.button("✅ Finalizar atendimento e enviar resumo", disabled=not telefone)

    # Botão de cancelar fica separado e "escondido" de propósito (dentro de
    # um expander, fechado por padrão, e só liberado depois de marcar a
    # caixinha de confirmação). Ele faz o oposto do "Finalizar": apaga o
    # resumo SEM mandar mensagem. Como ficava logo do lado do "Finalizar",
    # um clique errado ali faria o cliente nunca receber a mensagem do
    # atendimento de verdade — essa fricção extra é proposital, pra ninguém
    # apertar por engano.
    st.divider()
    cancelar_pendente = False
    with st.expander("⚠️ Cancelar o que ainda não enviei (só pra corrigir um teste que deu errado)"):
        st.warning(
            "Isso apaga o resumo que ia ser enviado pra esse telefone, SEM mandar "
            "mensagem pro cliente. **Só use isso se foi um teste/erro.** Se o "
            "atendimento foi de verdade, use o botão \"Finalizar atendimento e "
            "enviar resumo\" acima, não este."
        )
        confirmar_cancelamento = st.checkbox(
            "Sim, tenho certeza — não é um atendimento de verdade",
            key="ra_confirma_cancelar",
        )
        cancelar_pendente = st.button(
            "🧹 Cancelar mesmo assim (sem mandar mensagem)",
            disabled=not telefone or not confirmar_cancelamento,
        )

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
                        # Não manda WhatsApp na hora — só entra na fila do lado do
                        # Apps Script. Guardamos aqui também, localmente, só pra
                        # mostrar a lista "itens desta visita" na tela.
                        pendentes_por_telefone.setdefault(digitos_tel, []).append(servico)
                        msg = (
                            f"Serviço \"{servico}\" registrado! Saldo restante: {resultado.get('saldoRestante')}. "
                            "Ainda não mandei a mensagem pro cliente — clica em \"Finalizar atendimento\" "
                            "quando terminar de registrar tudo dessa visita."
                        )
                    else:
                        msg = (
                            f"Atendimento retroativo registrado! Saldo restante: {resultado.get('saldoRestante')}. "
                            "Nenhuma mensagem foi enviada (retroativo nunca manda)."
                        )
                    # Guarda a mensagem de sucesso. NÃO limpa o telefone aqui — só
                    # ao finalizar o atendimento (ver bloco "if finalizar" abaixo),
                    # porque o normal é marcar mais de um serviço seguido pro
                    # mesmo cliente antes de encerrar a visita.
                    st.session_state["_ra_sucesso_msg"] = msg
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

    if finalizar:
        try:
            resultado = sheets.finalizar_atendimento(telefone=telefone)
            if resultado.get("enviado"):
                servicos_enviados = resultado.get("servicos") or pendentes_deste_cliente
                msg = (
                    f"Resumo enviado pro cliente! Serviços dessa visita: "
                    + ", ".join(servicos_enviados) + "."
                )
            else:
                msg = (
                    "Não tinha nenhum serviço pendente pra esse telefone pra mandar "
                    "(talvez você só tenha feito lançamentos retroativos, ou já tinha finalizado antes)."
                )
            pendentes_por_telefone.pop(digitos_tel, None)
            st.session_state["_ra_sucesso_msg"] = msg
            st.session_state["_ra_limpar"] = True
            st.rerun()
        except Exception as e:
            formatar_erro(e)

    if cancelar_pendente:
        try:
            resultado = sheets.cancelar_atendimento_pendente(telefone=telefone)
            if resultado.get("cancelado"):
                msg = (
                    "Cancelado! Apaguei o que tava esperando pra esse telefone "
                    "(não mandei nenhuma mensagem pro cliente)."
                )
            else:
                msg = "Não tinha nada esperando pra esse telefone — nada pra cancelar."
            pendentes_por_telefone.pop(digitos_tel, None)
            st.session_state["_ra_sucesso_msg"] = msg
            st.session_state["_ra_limpar"] = True
            st.rerun()
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

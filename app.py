/**
 * API_Pacotes.gs
 * ------------------------------------------------------------
 * Endpoint novo, adicionado ao MESMO projeto Apps Script do Código.gs,
 * pra permitir que o app Python (Streamlit) registre atendimentos de
 * pacote sem passar pelo onEdit (que só funciona quando um humano edita
 * a planilha manualmente pela interface do Google Sheets — uma edição
 * feita via API não dispara o gatilho).
 *
 * Este arquivo USA as constantes e funções que já existem no Código.gs
 * (COL_TELEFONE, COL_SERVICO, normalizarTelefone_, registrarHistoricoPacote_,
 * etc.) — não redeclara nada, porque no Apps Script todos os arquivos .gs
 * de um mesmo projeto compartilham o mesmo escopo global. Se algum nome
 * de coluna ou função aqui não bater com o que já existe no seu Código.gs,
 * me avisa com a mensagem de erro que aparecer no log — é só ajustar o nome.
 *
 * ATUALIZADO 21/10/2026: o envio de mensagem agora usa
 * enviarMensagemComFallbackTemplate_ (definida no Código.gs) em vez de
 * botconversaSendMessage_ direto — assim, se o chat estiver fechado há
 * mais de 24h, cai automaticamente pro modelo aprovado pelo Meta
 * (Saldo_Pacote) em vez de simplesmente falhar.
 *
 * ============================================================
 * PASSO 1 — no Código.gs, dentro da função doPost(e), logo depois da linha:
 *
 *     const payload = JSON.parse(e.postData.contents);
 *
 * cole isto (uma linha só):
 *
 *     if (payload.acao) { return tratarAcaoAdmin_(payload); }
 *
 * Isso faz o doPost desviar pra cá quando quem está chamando é o app
 * Python (que sempre manda um campo "acao"), e continuar no fluxo normal
 * do SimplyBook quando não tem esse campo.
 * ============================================================
 */

// ID da planilha (fica no meio do link dela:
// https://docs.google.com/spreadsheets/d/ESTE_PEDAÇO_AQUI/edit).
// Precisamos dele aqui porque SpreadsheetApp.getActiveSpreadsheet() só
// funciona quando o script é chamado a partir da própria planilha (menu,
// onEdit etc.) — quando é chamado de fora, via Web App (como o app
// Python faz), ele não tem uma planilha "ativa" e devolve null, o que
// quebra com o erro "Cannot read properties of null (reading
// 'getSheetByName')". Usando openById(), a planilha certa é aberta
// direto, não importa de onde a chamada veio.
const ID_PLANILHA_PACOTES = '1w41BIXERQfD2pFvLn5V3TtO6N2uslyNxUpmeaj8CdRg';

// Coluna "Valor Unitário" (L) da aba Pacotes_Clientes — só existe nas linhas
// cadastradas pelo app Python (tela "Novo Pacote"), que já calcula e grava ali
// o preço real daquele pacote específico (considerando porte e eventuais
// ajustes manuais). Não existe no Código.gs porque o fluxo antigo (checkbox
// na planilha) nunca usou essa coluna.
const COL_VALOR_UNITARIO = 12;

// Token secreto que o app Python precisa mandar em toda chamada.
// Pra configurar o valor: Apps Script (editor) > engrenagem "Configurações
// do projeto" (barra lateral esquerda) > "Propriedades do script" >
// "Adicionar propriedade do script" > nome TOKEN_API_PACOTES, valor: uma
// senha longa qualquer que você inventar (ex: cole um texto aleatório).
// O mesmo valor vai no arquivo .env do app Python depois.
function getTokenApiPacotes_() {
  return PropertiesService.getScriptProperties().getProperty('TOKEN_API_PACOTES');
}

/**
 * Ponto de entrada de todas as ações administrativas vindas do app Python.
 * payload esperado: { acao, token, ...dadosDaAcao }
 */
function tratarAcaoAdmin_(payload) {
  const respostaErro = function (msg) {
    return ContentService.createTextOutput(JSON.stringify({ ok: false, erro: msg }))
      .setMimeType(ContentService.MimeType.JSON);
  };
  const respostaOk = function (dados) {
    return ContentService.createTextOutput(JSON.stringify(Object.assign({ ok: true }, dados)))
      .setMimeType(ContentService.MimeType.JSON);
  };

  const tokenEsperado = getTokenApiPacotes_();
  if (!tokenEsperado) {
    return respostaErro('TOKEN_API_PACOTES não configurado nas Propriedades do script.');
  }
  if (payload.token !== tokenEsperado) {
    return respostaErro('Token inválido.');
  }

  try {
    if (payload.acao === 'registrar_atendimento') {
      return respostaOk(apiRegistrarAtendimento_(payload));
    }
    if (payload.acao === 'novo_pacote') {
      return respostaOk(apiNovoPacote_(payload));
    }
    if (payload.acao === 'finalizar_atendimento') {
      return respostaOk(apiFinalizarAtendimento_(payload));
    }
    if (payload.acao === 'visualizar_resumo_pendente') {
      return respostaOk(apiVisualizarResumoPendente_(payload));
    }
    if (payload.acao === 'cancelar_atendimento_pendente') {
      return respostaOk(apiCancelarAtendimentoPendente_(payload));
    }
    if (payload.acao === 'finalizar_visita_completa') {
      return respostaOk(apiFinalizarVisitaCompleta_(payload));
    }
    return respostaErro('Ação desconhecida: ' + payload.acao);
  } catch (erro) {
    return respostaErro('Erro interno: ' + erro.message);
  }
}

/**
 * Ação "registrar_atendimento" — equivalente a marcar o checkbox
 * "Marcar Atendimento" na planilha, só que chamado pelo app Python.
 *
 * payload esperado:
 *   telefone            (obrigatório)
 *   servico             (obrigatório — mesmo texto usado na planilha, ex: "Banho")
 *   condominio          (opcional — ajuda a desempatar se o cliente tiver
 *                        pacotes com o mesmo serviço em condomínios diferentes)
 *   dataReconciliacao   (opcional, formato "YYYY-MM-DD" — se vier preenchido,
 *                        é tratado como lançamento retroativo: NÃO envia
 *                        WhatsApp, só atualiza saldo e histórico)
 */
function apiRegistrarAtendimento_(payload) {
  return processarAtendimentoPacote_(
    payload.telefone,
    payload.servico,
    payload.condominio || '',
    payload.dataReconciliacao || ''
  );
}

/**
 * Lógica central — mesma regra de negócio do checkbox "Marcar Atendimento"
 * (Case 1 do aoEditarPacotes), reescrita aqui como função independente pra
 * poder ser chamada tanto pela planilha (se um dia vocês quiserem) quanto
 * pela API. Usa os helpers que já existem no Código.gs.
 */
function processarAtendimentoPacote_(telefone, servico, condominio, dataReconciliacaoOuVazio, pularFila) {
  const planilha = SpreadsheetApp.openById(ID_PLANILHA_PACOTES);
  const aba = planilha.getSheetByName('Pacotes_Clientes');
  if (!aba) throw new Error('Aba Pacotes_Clientes não encontrada.');

  const telefoneNorm = normalizarTelefone_(telefone);
  const servicoNorm = normalizarServico_(servico);

  const dados = aba.getDataRange().getValues();
  let linhaAlvo = -1;

  for (let i = 1; i < dados.length; i++) {
    const linha = dados[i];
    const telefoneLinha = normalizarTelefone_(linha[COL_TELEFONE - 1]);
    const servicoLinha = normalizarServico_(linha[COL_SERVICO - 1]);
    if (telefoneLinha !== telefoneNorm || servicoLinha !== servicoNorm) continue;

    if (condominio) {
      const condLinha = String(linha[COL_CONDOMINIO - 1] || '').trim().toLowerCase();
      if (condLinha !== String(condominio).trim().toLowerCase()) continue;
    }

    const qtdComprada = Number(linha[COL_QTD_COMPRADA - 1]) || 0;
    const qtdUsada = Number(linha[COL_QTD_USADA - 1]) || 0;
    if (qtdComprada - qtdUsada <= 0) continue; // sem saldo nesse pacote, procura outro

    linhaAlvo = i;
    break;
  }

  if (linhaAlvo === -1) {
    throw new Error('Nenhum pacote com saldo disponível para telefone=' + telefone + ' servico=' + servico);
  }

  const numeroLinhaPlanilha = linhaAlvo + 1; // +1 porque getDataRange é 0-indexed e a planilha não
  const linha = dados[linhaAlvo];

  const qtdUsadaAtual = Number(linha[COL_QTD_USADA - 1]) || 0;
  const novaQtdUsada = qtdUsadaAtual + 1;
  const ehRetroativo = !!dataReconciliacaoOuVazio;

  const qtdComprada = Number(linha[COL_QTD_COMPRADA - 1]) || 0;
  const saldoRestante = qtdComprada - novaQtdUsada;

  aba.getRange(numeroLinhaPlanilha, COL_QTD_USADA).setValue(novaQtdUsada);
  // A coluna "Saldo" (COL_SALDO) é um valor gravado, não uma fórmula — antes
  // só a "Qtd Usada" era atualizada aqui, então o "Saldo" ficava congelado
  // no número de quando a linha foi criada/editada na mão. Isso fazia o
  // Painel de Pacotes E a mensagem de resumo pro cliente ("restam X de Y")
  // mostrarem saldo desatualizado depois de cada atendimento registrado.
  aba.getRange(numeroLinhaPlanilha, COL_SALDO).setValue(saldoRestante);
  aba.getRange(numeroLinhaPlanilha, COL_DATA_ULTIMO_USO).setValue(new Date());
  if (ehRetroativo) {
    aba.getRange(numeroLinhaPlanilha, COL_DATA_RECONCILIACAO).setValue(dataReconciliacaoOuVazio);
  }

  // IMPORTANTE: registrarHistoricoPacote_ (definida no Código.gs) espera os
  // argumentos NESSA ordem exata:
  //   (telefone, nome, condominio, servico, valor, bookingId,
  //    dataManualDDMMYYYY, qtdComprada, qtdUsadaAteAqui, saldoRestante)
  // A versão anterior daqui mandava só 5 argumentos soltos (telefone, nome,
  // servico, saldoRestante, ehRetroativo) — como a função recebe por
  // POSIÇÃO, cada valor foi parar numa casa errada (ex: o nome do serviço
  // caiu na coluna Condomínio, e o saldo caiu na coluna Serviço). É esse
  // o motivo da linha de histórico ter saído com os dados embaralhados.
  const condominioLinha = linha[COL_CONDOMINIO - 1] || '';
  const nomeLinha = linha[COL_NOME - 1] || '';
  const telefoneLinha = linha[COL_TELEFONE - 1];

  // O valor do serviço vem de preferência do "Valor Unitário" já gravado
  // nessa linha do pacote (calculado no cadastro em "Novo Pacote", já com
  // porte e eventuais ajustes considerados). A Tabela_Precos (usada como
  // fallback abaixo) guarda preço separado por PORTE pra serviços como
  // Banho/Tosa Completa (linhas "Banho P", "Banho M" etc.) — mas o nome do
  // serviço registrado por aqui não inclui porte (ex: só "Banho"), então a
  // busca por nome exato na Tabela_Precos não achava nada e o Valor saía
  // zerado no Histórico. Usando o Valor Unitário da própria linha, isso
  // não depende mais de bater o nome certinho com a Tabela_Precos.
  let valorServico = Number(linha[COL_VALOR_UNITARIO - 1]) || 0;
  if (!valorServico) {
    // Fallback pra pacotes antigos cadastrados antes de existir a coluna
    // "Valor Unitário" (ex: pelo fluxo antigo da planilha).
    valorServico = buscarValorTabelaPrecos_(condominioLinha, servico);
  }

  const dataManual = ehRetroativo ? formatarDataBR_(dataReconciliacaoOuVazio) : null;

  registrarHistoricoPacote_(
    telefoneLinha,
    nomeLinha,
    condominioLinha,
    servico,
    valorServico,
    null,
    dataManual,
    qtdComprada,
    novaQtdUsada,
    saldoRestante
  );

  // atualizarStatusPacoteAtivo_ espera o TELEFONE do cliente (pra achar o
  // contato certo no BotConversa) — antes estava recebendo o número da
  // linha da planilha por engano, então o saldo mostrado pro bot nunca
  // era atualizado de verdade.
  atualizarStatusPacoteAtivo_(telefoneLinha);

  // pularFila=true é usado pelo fluxo de "só grava quando Finalizar" (quando
  // quem chama já vai mandar UMA mensagem consolidada no final por conta
  // própria) — nesse caso não entra na fila antiga de pendências, senão
  // duplicaria.
  //
  // ATUALIZADO 21/10/2026: retroativo TAMBÉM entra na fila de pendências
  // agora (antes só o atendimento de hoje entrava, "!ehRetroativo &&
  // !pularFila"). O motivo: mandar mensagem nunca é mais automático pra
  // nenhum dos dois casos — é sempre um clique manual em "Enviar resumo
  // pro cliente" (ação finalizar_atendimento), então não tem risco de
  // avisar o cliente sem querer sobre um lançamento retroativo (ex: um
  // backfill de dados antigos). Isso só dá a você a OPÇÃO de, quando
  // quiser, mandar um resumo mesmo de um lançamento retroativo — você
  // decide, clicando ou não.
  if (!pularFila) {
    // adicionarServicoPendente_ espera (telefone, nome, servico) — antes
    // estava recebendo (telefone, servico, saldoRestante), o que fazia o
    // nome do serviço virar "nome do cliente" e o saldo virar "serviço"
    // na fila de mensagens consolidadas do WhatsApp.
    adicionarServicoPendente_(telefoneLinha, nomeLinha, servico);
  }

  return {
    telefone: linha[COL_TELEFONE - 1],
    nome: nomeLinha,
    servico: servico,
    saldoRestante: saldoRestante,
    retroativo: ehRetroativo,
    mensagemEnviada: !ehRetroativo
  };
}

/**
 * Fluxo novo: "só grava na planilha quando você clicar em Finalizar".
 *
 * Recebe a lista INTEIRA de serviços de uma visita de uma vez só (em vez de
 * um por um, como processarAtendimentoPacote_). Primeiro CONFERE se tem
 * saldo suficiente pra todos os serviços pedidos — sem escrever nada ainda.
 * Se faltar saldo pra qualquer um deles, cancela tudo e avisa qual foi, SEM
 * mexer na planilha. Só se passar na conferência é que processa de verdade,
 * um serviço de cada vez, e manda UMA mensagem de WhatsApp no final com o
 * resumo de tudo.
 *
 * Isso substitui o jeito antigo (cada "Registrar atendimento" já gravava na
 * hora, e só a mensagem ficava pendente) — agora nada toca na planilha até
 * você confirmar com "Finalizar", então se um teste der errado ou você
 * desistir no meio, dá pra simplesmente descartar sem precisar ir arrumar
 * nada na planilha depois.
 */
function validarEprocessarVisita_(telefone, condominio, servicosDaVisita) {
  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    if (!servicosDaVisita || servicosDaVisita.length === 0) {
      return { enviado: false, motivo: 'Nenhum serviço informado pra essa visita.' };
    }

    const planilha = SpreadsheetApp.openById(ID_PLANILHA_PACOTES);
    const aba = planilha.getSheetByName('Pacotes_Clientes');
    if (!aba) throw new Error('Aba Pacotes_Clientes não encontrada.');

    const telefoneNorm = normalizarTelefone_(telefone);
    const dados = aba.getDataRange().getValues();

    // Conta quantas vezes cada serviço aparece nessa visita (ex: Tosa
    // Higiênica x2), pra saber quanto de saldo precisa de cada um.
    const contagemPorServico = {};
    servicosDaVisita.forEach(function (s) {
      const chave = normalizarServico_(s);
      contagemPorServico[chave] = (contagemPorServico[chave] || 0) + 1;
    });

    const semSaldo = [];
    Object.keys(contagemPorServico).forEach(function (servicoNorm) {
      const necessario = contagemPorServico[servicoNorm];
      let saldoDisponivel = 0;
      for (let i = 1; i < dados.length; i++) {
        const linha = dados[i];
        if (normalizarTelefone_(linha[COL_TELEFONE - 1]) !== telefoneNorm) continue;
        if (normalizarServico_(linha[COL_SERVICO - 1]) !== servicoNorm) continue;
        if (condominio) {
          const condLinha = String(linha[COL_CONDOMINIO - 1] || '').trim().toLowerCase();
          if (condLinha !== String(condominio).trim().toLowerCase()) continue;
        }
        const qtdComprada = Number(linha[COL_QTD_COMPRADA - 1]) || 0;
        const qtdUsada = Number(linha[COL_QTD_USADA - 1]) || 0;
        saldoDisponivel += Math.max(qtdComprada - qtdUsada, 0);
      }
      if (saldoDisponivel < necessario) {
        semSaldo.push(servicoNorm + ' (precisa de ' + necessario + ', só tem ' + saldoDisponivel + ' de saldo)');
      }
    });

    if (semSaldo.length > 0) {
      throw new Error('Sem saldo suficiente: ' + semSaldo.join('; '));
    }

    // Passou na conferência — agora processa de verdade, um serviço de
    // cada vez (pularFila=true: não usa a fila antiga, a mensagem
    // consolidada é mandada aqui embaixo, uma única vez).
    let nomeCliente = '';
    servicosDaVisita.forEach(function (servico) {
      const resultado = processarAtendimentoPacote_(telefone, servico, condominio, '', true);
      nomeCliente = resultado.nome || nomeCliente;
    });

    const telefoneNormalizado = normalizarTelefone_(telefone);
    const mensagem = montarMensagemResumoAtendimento_(nomeCliente, servicosDaVisita, telefoneNormalizado);
    const subscriberId = botconversaGetSubscriberId_(telefoneNormalizado);
    enviarMensagemComFallbackTemplate_(subscriberId, mensagem);

    return { enviado: true, servicos: servicosDaVisita, nome: nomeCliente };
  } finally {
    lock.releaseLock();
  }
}

/**
 * Ação "finalizar_atendimento" — dispara AGORA a mensagem de WhatsApp
 * consolidada pro cliente, juntando todos os serviços que foram
 * registrados pra ele desde a última mensagem enviada (em vez de esperar
 * o temporizador de segundo plano). Chamada pelo botão "Finalizar
 * atendimento e enviar resumo" do app Python, quando você termina de
 * registrar tudo que o cliente usou naquela visita.
 *
 * payload esperado: { telefone }
 *
 * Se não houver nada pendente pra esse telefone (ex: só teve lançamento
 * retroativo), não dá erro — a resposta vem com enviado:false e um motivo.
 */
function apiFinalizarAtendimento_(payload) {
  if (!payload.telefone) throw new Error('telefone é obrigatório.');
  return finalizarAtendimentoPendente_(payload.telefone);
}

/**
 * Ação "visualizar_resumo_pendente" — devolve o texto da mensagem que SERIA
 * enviada agora pro cliente, sem enviar nada e sem apagar a fila de
 * pendências (ver visualizarResumoPendente_ no Código.gs). Usada pelo botão
 * "👀 Ver resumo antes de enviar" do app Python, antes de confirmar o envio
 * de verdade com "finalizar_atendimento".
 *
 * payload esperado: { telefone }
 */
function apiVisualizarResumoPendente_(payload) {
  if (!payload.telefone) throw new Error('telefone é obrigatório.');
  return visualizarResumoPendente_(payload.telefone);
}

/**
 * Ação "finalizar_visita_completa" — fluxo novo, onde o app Python só
 * guarda os serviços marcados NA TELA (sem gravar nada na planilha) até
 * você clicar em "Finalizar atendimento". Essa ação recebe a lista inteira
 * de serviços de uma vez, confere se tem saldo pra todos ANTES de gravar
 * qualquer coisa, e só então grava tudo + manda a mensagem consolidada.
 *
 * payload esperado: { telefone, condominio (opcional), servicos: [...] }
 */
function apiFinalizarVisitaCompleta_(payload) {
  if (!payload.telefone) throw new Error('telefone é obrigatório.');
  if (!payload.servicos || !payload.servicos.length) throw new Error('servicos é obrigatório (lista não pode ser vazia).');
  return validarEprocessarVisita_(payload.telefone, payload.condominio || '', payload.servicos);
}

/**
 * Ação "cancelar_atendimento_pendente" — apaga a fila pendente de um
 * telefone SEM mandar mensagem nenhuma pro cliente. Usada pelo botão
 * "🧹 Cancelar o que ainda não enviei" do app Python, pra limpar um teste
 * que deu errado antes que ele se misture com o próximo atendimento de
 * verdade daquele mesmo telefone.
 *
 * payload esperado: { telefone }
 */
function apiCancelarAtendimentoPendente_(payload) {
  if (!payload.telefone) throw new Error('telefone é obrigatório.');
  return cancelarAtendimentoPendente_(payload.telefone);
}

/**
 * Ação "novo_pacote" — equivalente a adicionar uma linha nova na
 * Pacotes_Clientes quando o cliente compra um pacote.
 *
 * payload esperado:
 *   telefone, nome, condominio, servico, porte,
 *   qtdComprada, valorTotal, dataCompra (formato "YYYY-MM-DD")
 */
function apiNovoPacote_(payload) {
  const planilha = SpreadsheetApp.openById(ID_PLANILHA_PACOTES);
  const aba = planilha.getSheetByName('Pacotes_Clientes');
  if (!aba) throw new Error('Aba Pacotes_Clientes não encontrada.');

  const novaLinha = [];
  novaLinha[COL_TELEFONE - 1] = payload.telefone;
  novaLinha[COL_NOME - 1] = payload.nome || '';
  novaLinha[COL_CONDOMINIO - 1] = payload.condominio || '';
  novaLinha[COL_SERVICO - 1] = payload.servico;
  novaLinha[COL_QTD_COMPRADA - 1] = Number(payload.qtdComprada) || 0;
  novaLinha[COL_QTD_USADA - 1] = 0;

  // Preenche até o tamanho da tabela existente pra não desalinhar colunas
  // que não usamos aqui.
  const numColunas = aba.getLastColumn();
  for (let c = 0; c < numColunas; c++) {
    if (novaLinha[c] === undefined) novaLinha[c] = '';
  }

  aba.appendRow(novaLinha);
  const numeroLinhaPlanilha = aba.getLastRow();

  // COL_VALOR_TOTAL não existe no Código.gs (só existe COL_VALOR_PAGO) —
  // antes isso fazia o valor cair sempre na ÚLTIMA coluna da planilha, não
  // na coluna certa de valor pago.
  if (payload.valorTotal !== undefined) {
    aba.getRange(numeroLinhaPlanilha, COL_VALOR_PAGO || numColunas).setValue(Number(payload.valorTotal) || 0);
  }
  if (payload.dataCompra) {
    aba.getRange(numeroLinhaPlanilha, COL_DATA_COMPRA || numColunas).setValue(payload.dataCompra);
  }

  // Mesma correção do processarAtendimentoPacote_: atualizarStatusPacoteAtivo_
  // espera o telefone do cliente, não o número da linha.
  atualizarStatusPacoteAtivo_(payload.telefone);

  return { linha: numeroLinhaPlanilha, telefone: payload.telefone, servico: payload.servico };
}

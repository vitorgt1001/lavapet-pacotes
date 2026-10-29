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
 * ATUALIZADO 28/10/2026: nova ação "listar_candidatos_pacote" + ajuste no
 * processarAtendimentoPacote_ pra resolver o seguinte problema: quando um
 * cliente tem mais de um pacote pro MESMO serviço genérico (ex: "Banho P"
 * pro Bart e "Banho M" pro Romeu — os dois normalizam pra "banho"), o
 * sistema escolhia sozinho o primeiro pacote com saldo, sem perguntar nada
 * — risco de descontar do pacote do pet errado. Agora, antes de marcar um
 * serviço em "Registrar Atendimento", o app Python chama
 * listar_candidatos_pacote pra saber se existe mais de um pacote
 * compatível; se tiver, mostra uma lista (porte + nome do pet, se
 * preenchido + saldo) pra você escolher, e manda o texto EXATO da coluna
 * Serviço daquele pacote (ex: "Banho P") em vez do nome genérico. O
 * processarAtendimentoPacote_ agora dá PREFERÊNCIA a um match exato desse
 * texto (bate com a linha certa) e só cai pro comportamento antigo
 * (primeiro match normalizado) se não vier um texto exato que bata com
 * nenhuma linha — então nada muda pra quem só tem um pacote por serviço.
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
    if (payload.acao === 'listar_candidatos_pacote') {
      return respostaOk(apiListarCandidatosPacote_(payload));
    }
    if (payload.acao === 'estornar_atendimento') {
      return respostaOk(apiEstornarAtendimento_(payload));
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
 * Ação "listar_candidatos_pacote" — devolve todos os pacotes desse
 * telefone que têm saldo disponível pro serviço informado (depois de
 * normalizar, então "Banho" encontra tanto "Banho P" quanto "Banho M").
 * Não grava nada, só lê — usada pelo app Python ANTES de marcar um
 * serviço em "Registrar Atendimento", pra saber se precisa perguntar
 * qual pacote específico (quando tem mais de um candidato).
 *
 * payload esperado: { telefone, servico, condominio (opcional) }
 */
function apiListarCandidatosPacote_(payload) {
  if (!payload.telefone) throw new Error('telefone é obrigatório.');
  if (!payload.servico) throw new Error('servico é obrigatório.');
  return listarCandidatosPacote_(payload.telefone, payload.servico, payload.condominio || '');
}

/**
 * TESTE MANUAL — roda só pelo editor do Apps Script (não é chamada por
 * ninguém mais), pra conferir diretamente o que listarCandidatosPacote_
 * está encontrando pro telefone da Neide, sem depender do app Python nem
 * da internet. Clica dentro desta função e aperta ▶ Executar, depois olha
 * o resultado em "Execuções" (ver LOG abaixo).
 */
function testarListarCandidatosPacote_() {
  const resultado = listarCandidatosPacote_('11957323840', 'Banho', 'Ventana');
  Logger.log('RESULTADO: ' + JSON.stringify(resultado, null, 2));
  Logger.log('Quantos candidatos achou: ' + resultado.candidatos.length);
}

function listarCandidatosPacote_(telefone, servico, condominio) {
  const planilha = SpreadsheetApp.openById(ID_PLANILHA_PACOTES);
  const aba = planilha.getSheetByName('Pacotes_Clientes');
  if (!aba) throw new Error('Aba Pacotes_Clientes não encontrada.');

  const telefoneNorm = normalizarTelefone_(telefone);
  const servicoNorm = normalizarServico_(servico);

  // Procura a coluna "Nome do Pet" pelo texto do cabeçalho (pode não
  // existir ainda, se você não tiver criado ela na planilha — nesse caso
  // nomePet sempre volta vazio, sem dar erro).
  const cabecalho = aba.getRange(1, 1, 1, aba.getLastColumn()).getValues()[0];
  const colNomePet = cabecalho.findIndex(function (titulo) {
    return String(titulo || '').trim().toLowerCase() === 'nome do pet';
  });

  const dados = aba.getDataRange().getValues();
  const candidatos = [];

  for (let i = 1; i < dados.length; i++) {
    const linha = dados[i];
    if (normalizarTelefone_(linha[COL_TELEFONE - 1]) !== telefoneNorm) continue;

    const servicoLinhaBruto = String(linha[COL_SERVICO - 1] || '').trim();
    if (!servicoLinhaBruto || normalizarServico_(servicoLinhaBruto) !== servicoNorm) continue;

    if (condominio) {
      const condLinha = String(linha[COL_CONDOMINIO - 1] || '').trim().toLowerCase();
      if (condLinha !== String(condominio).trim().toLowerCase()) continue;
    }

    const qtdComprada = Number(linha[COL_QTD_COMPRADA - 1]) || 0;
    const qtdUsada = Number(linha[COL_QTD_USADA - 1]) || 0;
    const saldo = qtdComprada - qtdUsada;
    if (saldo <= 0) continue; // sem saldo, não é candidato

    candidatos.push({
      servico: servicoLinhaBruto,
      nomePet: colNomePet !== -1 ? String(linha[colNomePet] || '').trim() : '',
      condominio: String(linha[COL_CONDOMINIO - 1] || '').trim(),
      saldo: saldo
    });
  }

  return { candidatos: candidatos };
}

/**
 * Ação "estornar_atendimento" — desfaz um atendimento específico já
 * gravado: devolve 1 no saldo do pacote (Qtd Usada -1, Saldo +1) e apaga a
 * linha correspondente do Historico_Pacotes. NÃO manda mensagem nenhuma
 * pro cliente. Usada pelo botão "↩️ Desfazer este atendimento" na tela
 * "Histórico do Cliente" do app Python.
 *
 * payload esperado: { telefone, servico, dataHora }
 *   servico  = texto EXATO da coluna Serviço (ex: "Banho P")
 *   dataHora = texto EXATO da coluna "Data e Hora" do Historico_Pacotes,
 *              como aparece na leitura da planilha (ex: "16/10/2026
 *              00:00:00") — é assim que a gente sabe qual linha exata
 *              apagar, mesmo que existam várias parecidas.
 */
function apiEstornarAtendimento_(payload) {
  if (!payload.telefone) throw new Error('telefone é obrigatório.');
  if (!payload.servico) throw new Error('servico é obrigatório.');
  if (!payload.dataHora) throw new Error('dataHora é obrigatório.');
  return estornarAtendimento_(payload.telefone, payload.servico, payload.dataHora);
}

function estornarAtendimento_(telefone, servicoExato, dataHoraTexto) {
  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const planilha = SpreadsheetApp.openById(ID_PLANILHA_PACOTES);
    const abaHist = planilha.getSheetByName(ABA_HISTORICO_PACOTES);
    const abaPacotes = planilha.getSheetByName('Pacotes_Clientes');
    if (!abaHist) throw new Error('Aba Historico_Pacotes não encontrada.');
    if (!abaPacotes) throw new Error('Aba Pacotes_Clientes não encontrada.');

    const telefoneNorm = normalizarTelefone_(telefone);
    const servicoAlvo = String(servicoExato).trim();
    const dataHoraAlvo = String(dataHoraTexto).trim();

    const formatarDataHoraLinha = function (valor) {
      return valor instanceof Date
        ? Utilities.formatDate(valor, 'GMT-3', 'dd/MM/yyyy HH:mm:ss')
        : String(valor || '').trim();
    };

    // Acha a linha do Historico_Pacotes a apagar — telefone + serviço
    // exato + data/hora exata batendo. Procura de baixo pra cima (mais
    // recente primeiro), já que é o caso mais comum de querer desfazer.
    const dadosHist = abaHist.getDataRange().getValues();
    let linhaHistAlvo = -1;
    for (let i = dadosHist.length - 1; i >= 1; i--) {
      const linha = dadosHist[i];
      if (
        normalizarTelefone_(linha[1]) === telefoneNorm &&
        String(linha[4] || '').trim() === servicoAlvo &&
        formatarDataHoraLinha(linha[0]) === dataHoraAlvo
      ) {
        linhaHistAlvo = i;
        break;
      }
    }
    if (linhaHistAlvo === -1) {
      throw new Error('Não achei essa linha no Historico_Pacotes (talvez já tenha sido estornada).');
    }

    // Acha a linha correspondente em Pacotes_Clientes (telefone + serviço exato).
    const dadosPacotes = abaPacotes.getDataRange().getValues();
    let linhaPacoteAlvo = -1;
    for (let i = 1; i < dadosPacotes.length; i++) {
      if (
        normalizarTelefone_(dadosPacotes[i][COL_TELEFONE - 1]) === telefoneNorm &&
        String(dadosPacotes[i][COL_SERVICO - 1] || '').trim() === servicoAlvo
      ) {
        linhaPacoteAlvo = i;
        break;
      }
    }
    if (linhaPacoteAlvo === -1) {
      throw new Error('Não achei o pacote correspondente em Pacotes_Clientes pra esse telefone/serviço.');
    }

    const numLinhaPacote = linhaPacoteAlvo + 1;
    const qtdUsadaAtual = Number(dadosPacotes[linhaPacoteAlvo][COL_QTD_USADA - 1]) || 0;
    const qtdComprada = Number(dadosPacotes[linhaPacoteAlvo][COL_QTD_COMPRADA - 1]) || 0;
    const novaQtdUsada = Math.max(qtdUsadaAtual - 1, 0);
    const novoSaldo = qtdComprada - novaQtdUsada;

    abaPacotes.getRange(numLinhaPacote, COL_QTD_USADA).setValue(novaQtdUsada);
    abaPacotes.getRange(numLinhaPacote, COL_SALDO).setValue(novoSaldo);

    // Apaga a linha do Historico_Pacotes.
    abaHist.deleteRow(linhaHistAlvo + 1);

    // Recalcula a Data Último Uso a partir do que sobrou no Historico_Pacotes
    // pra esse telefone+serviço (pega a mais recente que restou), ou deixa
    // em branco se não sobrou nenhuma — senão ficaria apontando pra uma
    // data que acabou de ser estornada.
    const dadosHistDepois = abaHist.getDataRange().getValues();
    let novaDataUltimoUso = '';
    for (let i = 1; i < dadosHistDepois.length; i++) {
      const linha = dadosHistDepois[i];
      if (normalizarTelefone_(linha[1]) === telefoneNorm && String(linha[4] || '').trim() === servicoAlvo) {
        const dataLinha = linha[0] instanceof Date ? linha[0] : null;
        if (dataLinha && (!novaDataUltimoUso || dataLinha > novaDataUltimoUso)) {
          novaDataUltimoUso = dataLinha;
        }
      }
    }
    abaPacotes.getRange(numLinhaPacote, COL_DATA_ULTIMO_USO).setValue(novaDataUltimoUso || '');

    const telefoneLinha = dadosPacotes[linhaPacoteAlvo][COL_TELEFONE - 1];
    atualizarStatusPacoteAtivo_(telefoneLinha);

    return {
      estornado: true,
      telefone: telefoneLinha,
      servico: servicoAlvo,
      novaQtdUsada: novaQtdUsada,
      novoSaldo: novoSaldo,
    };
  } finally {
    lock.releaseLock();
  }
}

/**
 * Lógica central — mesma regra de negócio do checkbox "Marcar Atendimento"
 * (Case 1 do aoEditarPacotes), reescrita aqui como função independente pra
 * poder ser chamada tanto pela planilha (se um dia vocês quiserem) quanto
 * pela API. Usa os helpers que já existem no Código.gs.
 *
 * ATUALIZADO 28/10/2026: quando "servico" bate EXATAMENTE (ignorando
 * maiúscula/minúscula e espaços) com o texto da coluna Serviço de alguma
 * linha candidata (ex: você passou "Banho P"), essa linha tem prioridade
 * sobre o comportamento antigo (primeiro match normalizado) — é assim que
 * a tela de desambiguação do "Registrar Atendimento" aponta pro pacote
 * certo quando o cliente tem mais de um pacote pro mesmo serviço
 * genérico. Se "servico" vier genérico (ex: só "Banho", sem porte), nada
 * muda: cai no mesmo comportamento de sempre (primeiro match com saldo).
 */
function processarAtendimentoPacote_(telefone, servico, condominio, dataReconciliacaoOuVazio, pularFila) {
  const planilha = SpreadsheetApp.openById(ID_PLANILHA_PACOTES);
  const aba = planilha.getSheetByName('Pacotes_Clientes');
  if (!aba) throw new Error('Aba Pacotes_Clientes não encontrada.');

  const telefoneNorm = normalizarTelefone_(telefone);
  const servicoNorm = normalizarServico_(servico);
  const servicoTextoBusca = String(servico || '').trim().toLowerCase();

  const dados = aba.getDataRange().getValues();
  let linhaAlvoExata = -1;
  let linhaAlvoNormalizada = -1;

  for (let i = 1; i < dados.length; i++) {
    const linha = dados[i];
    const telefoneLinha = normalizarTelefone_(linha[COL_TELEFONE - 1]);
    const servicoLinhaBruto = String(linha[COL_SERVICO - 1] || '').trim();
    const servicoLinha = normalizarServico_(servicoLinhaBruto);
    if (telefoneLinha !== telefoneNorm || servicoLinha !== servicoNorm) continue;

    if (condominio) {
      const condLinha = String(linha[COL_CONDOMINIO - 1] || '').trim().toLowerCase();
      if (condLinha !== String(condominio).trim().toLowerCase()) continue;
    }

    const qtdComprada = Number(linha[COL_QTD_COMPRADA - 1]) || 0;
    const qtdUsada = Number(linha[COL_QTD_USADA - 1]) || 0;
    if (qtdComprada - qtdUsada <= 0) continue; // sem saldo nesse pacote, procura outro

    if (linhaAlvoNormalizada === -1) {
      linhaAlvoNormalizada = i;
    }
    if (linhaAlvoExata === -1 && servicoLinhaBruto.toLowerCase() === servicoTextoBusca) {
      linhaAlvoExata = i;
    }
  }

  const linhaAlvo = linhaAlvoExata !== -1 ? linhaAlvoExata : linhaAlvoNormalizada;

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
  // "Data Último Uso" estava sempre recebendo new Date() (a data/hora real de
  // quando você clicou no botão) — faz sentido pro atendimento de HOJE, mas
  // pra um lançamento retroativo isso grava a data errada (ex: você registra
  // hoje um banho que na verdade foi em 20/09, e o Painel/resumo mostravam
  // "último uso hoje" em vez de 20/09). Agora, se for retroativo, usa a data
  // que você escolheu (dataReconciliacaoOuVazio) em vez da data de agora.
  const dataUltimoUso = (ehRetroativo && dataReconciliacaoOuVazio)
    ? new Date(dataReconciliacaoOuVazio + 'T00:00:00')
    : new Date();
  aba.getRange(numeroLinhaPlanilha, COL_DATA_ULTIMO_USO).setValue(dataUltimoUso);
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
  // Guarda o texto EXATO do serviço dessa linha (ex: "Banho P") pro
  // histórico e pra fila de pendências — mais preciso que o "servico"
  // genérico que pode ter vindo da tela (ex: só "Banho").
  const servicoExatoLinha = String(linha[COL_SERVICO - 1] || '').trim() || servico;

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
    servicoExatoLinha,
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
    // adicionarServicoPendente_ espera (telefone, nome, servico, dataItemBR)
    // — antes estava recebendo (telefone, servico, saldoRestante), o que
    // fazia o nome do serviço virar "nome do cliente" e o saldo virar
    // "serviço" na fila de mensagens consolidadas do WhatsApp.
    //
    // Manda a data REAL do item (dataManual, se for retroativo; senão hoje)
    // — antes a fila só guardava o nome do serviço, sem data nenhuma, então
    // a mensagem de resumo chamava TUDO de "Atendimento de hoje", mesmo um
    // lançamento retroativo de semanas atrás.
    const dataItemBR = dataManual || Utilities.formatDate(new Date(), 'GMT-3', 'dd/MM/yyyy');
    adicionarServicoPendente_(telefoneLinha, nomeLinha, servicoExatoLinha, dataItemBR);
  }

  return {
    telefone: linha[COL_TELEFONE - 1],
    nome: nomeLinha,
    servico: servicoExatoLinha,
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

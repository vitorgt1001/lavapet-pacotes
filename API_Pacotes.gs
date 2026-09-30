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
function processarAtendimentoPacote_(telefone, servico, condominio, dataReconciliacaoOuVazio) {
  const planilha = SpreadsheetApp.getActiveSpreadsheet();
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

  aba.getRange(numeroLinhaPlanilha, COL_QTD_USADA).setValue(novaQtdUsada);
  aba.getRange(numeroLinhaPlanilha, COL_DATA_ULTIMO_USO).setValue(new Date());
  if (ehRetroativo) {
    aba.getRange(numeroLinhaPlanilha, COL_DATA_RECONCILIACAO).setValue(dataReconciliacaoOuVazio);
  }

  const qtdComprada = Number(linha[COL_QTD_COMPRADA - 1]) || 0;
  const saldoRestante = qtdComprada - novaQtdUsada;

  registrarHistoricoPacote_(
    linha[COL_TELEFONE - 1],
    linha[COL_NOME - 1] || '',
    servico,
    saldoRestante,
    ehRetroativo
  );

  atualizarStatusPacoteAtivo_(numeroLinhaPlanilha);

  if (!ehRetroativo) {
    adicionarServicoPendente_(linha[COL_TELEFONE - 1], servico, saldoRestante);
  }

  return {
    telefone: linha[COL_TELEFONE - 1],
    servico: servico,
    saldoRestante: saldoRestante,
    retroativo: ehRetroativo,
    mensagemEnviada: !ehRetroativo
  };
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
  const planilha = SpreadsheetApp.getActiveSpreadsheet();
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

  if (payload.valorTotal !== undefined) {
    aba.getRange(numeroLinhaPlanilha, COL_VALOR_TOTAL || numColunas).setValue(Number(payload.valorTotal) || 0);
  }
  if (payload.dataCompra) {
    aba.getRange(numeroLinhaPlanilha, COL_DATA_COMPRA || numColunas).setValue(payload.dataCompra);
  }

  atualizarStatusPacoteAtivo_(numeroLinhaPlanilha);

  return { linha: numeroLinhaPlanilha, telefone: payload.telefone, servico: payload.servico };
}

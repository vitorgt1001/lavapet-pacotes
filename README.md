# LavaPet — Controle de Pacotes (app em Python)

App simples feito em Streamlit pra substituir o controle manual de
pacotes na planilha. Ele continua usando a mesma planilha Google Sheets
por trás (você não perde nada do que já existe), só que com uma
interface mais profissional e com menos chance de erro.

O BotConversa continua exatamente como está hoje — esse app não mexe no
atendimento por WhatsApp, só no controle de pacotes.

---

## O que você vai precisar fazer (uma vez só)

### 1. Criar a conta de serviço no Google Cloud

Isso é uma "identidade robô" que o app Python usa pra acessar sua
planilha, sem precisar do seu login pessoal do Google toda vez.

1. Acesse https://console.cloud.google.com/
2. Crie um projeto novo (ou use um existente) — nome sugerido: `lavapet-pacotes`.
3. No menu lateral, vá em **APIs e serviços > Biblioteca**, procure por
   **Google Sheets API** e clique em **Ativar**.
4. Ainda em **APIs e serviços**, vá em **Credenciais > Criar credenciais
   > Conta de serviço**.
5. Dê um nome (ex: `lavapet-pacotes-app`) e clique em **Concluir**
   (pode pular as permissões opcionais).
6. Clique na conta de serviço que acabou de criar, vá na aba **Chaves >
   Adicionar chave > Criar nova chave > JSON**. Isso baixa um arquivo
   `.json` pro seu computador.
7. Renomeie esse arquivo pra `credenciais_google.json` e coloque ele
   dentro desta mesma pasta (`pacotes_app/`).
   ⚠️ Esse arquivo dá acesso à sua planilha — não compartilhe ele com
   ninguém, não suba pra nenhum lugar público (GitHub, WhatsApp, etc.).
8. Copie o "e-mail" da conta de serviço (algo como
   `lavapet-pacotes-app@lavapet-pacotes.iam.gserviceaccount.com` —
   aparece na mesma tela de credenciais).

### 2. Compartilhar a planilha com a conta de serviço

1. Abra sua planilha do LavaPet no Google Sheets.
2. Clique em **Compartilhar** (canto superior direito).
3. Cole o e-mail da conta de serviço (passo 8 acima) e dê permissão de
   **Editor**.
4. Copie o **ID da planilha** — é o pedaço do link entre `/d/` e
   `/edit`:
   `https://docs.google.com/spreadsheets/d/ESTE_PEDACO_AQUI/edit`

### 3. Adicionar a API nova no Apps Script

1. Abra o editor do Apps Script do seu projeto (o mesmo onde está o
   `Código.gs`).
2. Crie um arquivo novo: **Arquivo > Novo > Script**, nomeie
   `API_Pacotes` e cole o conteúdo do arquivo `API_Pacotes.gs` (está
   junto com este README).
3. Abra o `Código.gs`, ache a função `doPost(e)`, e logo depois da
   linha:
   ```
   const payload = JSON.parse(e.postData.contents);
   ```
   cole esta linha:
   ```
   if (payload.acao) { return tratarAcaoAdmin_(payload); }
   ```
4. Configure o token secreto: clique na engrenagem **Configurações do
   projeto** (barra lateral esquerda) > **Propriedades do script** >
   **Adicionar propriedade do script**.
   - Nome: `TOKEN_API_PACOTES`
   - Valor: invente uma senha longa (ex: junte letras e números
     aleatórios). Guarde esse valor, você vai usar de novo no passo 5.
5. Clique em **Implantar > Gerenciar implantações**. Se você já tem uma
   implantação de Web App (a que o SimplyBook usa pro webhook), clique
   no lápis (editar) > **Nova versão** > **Implantar**, pra essa
   mudança entrar em vigor. Copie a **URL do Web App** — é a mesma URL
   de sempre, só que agora também atende os pedidos do app Python.

   ⚠️ Importante: como isso mexe no `doPost`, é preciso gerar uma
   **nova versão** da implantação (não é automático), senão o
   SimplyBook continua batendo na versão antiga do código.

### 4. Configurar o app Python

1. Copie o arquivo `.env.example` e renomeie a cópia pra `.env`
   (mesma pasta).
2. Abra o `.env` num editor de texto simples (Bloco de Notas serve) e
   preencha:
   - `SPREADSHEET_ID`: o ID copiado no passo 2.4
   - `GOOGLE_SERVICE_ACCOUNT_FILE`: deixe `credenciais_google.json`
     (se você renomeou o arquivo diferente, ajuste aqui)
   - `APPS_SCRIPT_URL`: a URL copiada no passo 3.5
   - `APPS_SCRIPT_TOKEN`: o mesmo valor que você colocou em
     `TOKEN_API_PACOTES` no passo 3.4

### 5. Instalar e rodar

Precisa ter Python instalado no computador (versão 3.9 ou mais nova).
Abra um terminal dentro da pasta `pacotes_app/` e rode:

```
pip install -r requirements.txt
streamlit run app.py
```

Isso abre o app no navegador automaticamente (geralmente em
`http://localhost:8501`). Pra parar, volta no terminal e aperta
`Ctrl+C`.

Da próxima vez, é só repetir o `streamlit run app.py` (não precisa
instalar de novo).

---

## Hospedar na internet (pra acesso de outra cidade)

Como sua cliente está em outra cidade, rodar só no seu computador não
resolve — ela precisa acessar de um lugar fora da sua rede. Pra isso,
use o **Streamlit Community Cloud** (gratuito):

1. Crie uma conta em https://github.com (se ainda não tiver).
2. Crie um repositório novo (pode ser **privado**) e suba os arquivos
   desta pasta — pelo próprio site do GitHub, em **Add file > Upload
   files**, arrastando os arquivos (não suba o `.env` nem o
   `credenciais_google.json` — o `.gitignore` já deste pacote impede
   isso se você usar `git`, mas no upload manual pelo site, cuidado pra
   não arrastar esses dois).
3. Acesse https://streamlit.io/cloud, entre com sua conta do GitHub e
   clique em **New app**, escolhendo o repositório que você acabou de
   criar e o arquivo `app.py`.
4. Antes de clicar em Deploy, abra **Advanced settings > Secrets** e
   cole o conteúdo do arquivo `.streamlit/secrets.toml.example` (que
   está nesta pasta) com os valores reais preenchidos — é o mesmo
   conteúdo do `.env`, só que em outro formato, mais o
   `[gcp_service_account]` com todo o conteúdo do seu arquivo `.json`
   colado campo por campo, e uma `APP_PASSWORD` (a senha que você e ela
   vão usar pra entrar).
5. Clique em **Deploy**. Depois de alguns minutos, a Streamlit Cloud te
   dá um link (tipo `lavapet-pacotes.streamlit.app`) — esse link
   funciona de qualquer lugar, pros dois.

O app já está preparado pra isso: se você configurar `APP_PASSWORD`,
ele passa a pedir senha antes de mostrar qualquer tela; sem ela
configurada (uso só local, no seu computador), continua abrindo direto,
sem pedir nada.

### Só você, no seu computador, sem hospedar

Se por enquanto quiser só testar sozinho, sem a Patrícia/cliente, pode
pular a hospedagem: `streamlit run app.py` mostra uma "Network URL"
que funciona pra qualquer pessoa na MESMA rede Wi-Fi que você — mas só
enquanto seu computador estiver ligado e o app rodando.

---

## O que cada tela faz

- **📊 Painel de Pacotes**: lista todos os pacotes cadastrados, com
  saldo calculado (comprado − usado), filtro por condomínio e opção de
  mostrar só quem ainda tem saldo.
- **➕ Novo Pacote**: cadastra um pacote comprado por um cliente.
  Escreve direto na planilha (aba `Pacotes_Clientes`).
- **✅ Registrar Atendimento**: desconta 1 do saldo do pacote do
  cliente, chama a mesma lógica que já existe no Apps Script (histórico
  + mensagem de WhatsApp com o saldo, exceto se marcar como
  retroativo).
- **📜 Histórico do Cliente**: busca por telefone e mostra todos os
  atendimentos já registrados pra aquele cliente.

## Se der erro de "coluna não encontrada"

O app tenta casar os nomes das colunas do app com os cabeçalhos reais
da sua planilha (ex: "Telefone", "Nome", "Condomínio"...). Se algum
nome estiver escrito diferente na planilha (acento, espaço, abreviação),
o app avisa exatamente qual nome não achou. Me manda a mensagem de erro
que eu ajusto o código pra bater certinho.

## Arquivos desta pasta

- `app.py` — a interface (as 4 telas)
- `sheets.py` — conexão com a planilha e com a API do Apps Script
- `catalogo.py` — lista de condomínios/serviços/preços de referência
- `requirements.txt` — lista de pacotes Python necessários
- `.env.example` — modelo de configuração (copie pra `.env` e preencha)
- `README.md` — este arquivo

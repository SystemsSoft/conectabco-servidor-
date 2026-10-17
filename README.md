# Servidor – Marcelo Bonifácio Gestão Imobiliária

API em **Python + FastAPI** que alimenta o front-end Flutter (`marceloimob_gestao`).
Banco: **MySQL 8.4 no AWS Lightsail** (SQLAlchemy 2 + migrações Alembic).

Módulos prontos:
- **Cadastros e CRM** — imóveis, contatos com perfil de interesse, cruzamento
  de perfil e Central de Relacionamento.
- **Administração de Locação** — contratos, despesas, cobranças (boletos e
  recibos) e repasses.
- **Administração de Vendas** — vendas, financiamento próprio (parcelas) e
  comissões.
- **Locação por Temporada** — reservas e bloqueios do calendário, com
  checagem de datas sobrepostas no servidor.
- **Financeiro** — contas a pagar e a receber, contas bancárias, extrato e
  conciliação, boletos, índices de correção e configuração de multa/juros.
- **Fiscal** — declarante da DIMOB (a DIMOB e o IR são montados no app com os
  dados de Locação, Vendas e CRM).
- **Contratos e Relatórios** — "Meus modelos" de contrato (o catálogo de
  modelos prontos acompanha o app).
- **Equipe e Segurança** — login, usuários e permissões, sessões, histórico de
  atividades, fila de atendimento, comissões da equipe e chat interno.
- **Personalização** — logotipo e dados da imobiliária usados nos documentos.
- **Manutenção** — pauta e diário de manutenção (usada na Locação e nas Vendas).

## Instalação

```bash
python3 -m venv .venv          # o PyCharm já criou a .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env .env           # preencha usuário, senha e nome do banco
```

### Banco no Lightsail

1. No console do Lightsail, em **Networking** do banco, ative o **modo público**
   (ou rode o servidor numa instância Lightsail na mesma região).
2. Crie o schema, se ainda não existir:
   ```sql
   CREATE DATABASE marceloimob CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
   ```
3. (Recomendado) baixe o certificado da região e informe em `DB_SSL_CA`:
   `https://truststore.pki.rds.amazonaws.com/us-east-2/us-east-2-bundle.pem`
4. Crie as tabelas:
   ```bash
   .venv/bin/alembic upgrade head
   ```

Teste a conexão em `GET /saude/banco` com o servidor rodando.

## Primeiro acesso (login)

Toda a API exige login. No `.env`, defina `JWT_SECRET` (chave longa e secreta
que assina os tokens; sem ela, todos precisam entrar de novo a cada reinício):

```bash
python -c "import secrets;print(secrets.token_urlsafe(48))"
```

Crie o administrador (pede nome, usuário de login — ex.: Marcelo — e senha;
também serve para redefinir a senha dele se esquecer):

```bash
.venv/bin/python gerenciar.py criar-admin
```

Os demais usuários são criados no app, em Equipe e Segurança > Usuários.

## Rodando

```bash
.venv/bin/python main.py       # http://localhost:8000
```

Documentação interativa (Swagger): **http://localhost:8000/docs**

## Produção (AWS EC2)

Servidor `18.191.168.173` (Amazon Linux 2023, usuário SSH `ec2-user`):

| O quê | Onde |
|---|---|
| Código e `.env` (dono `marceloimob`, permissão 600) | `/opt/marceloimob` |
| Fotos, vídeos e arquivos enviados | `/var/lib/marceloimob/arquivos` |
| Serviço (uvicorn, 2 workers, 127.0.0.1:8000) | `systemctl status marceloimob` · `journalctl -u marceloimob -f` |
| nginx (porta 80 → serviço, uploads até 300 MB) | `/etc/nginx/default.d/marceloimob.conf` |
| Limpeza diária de arquivos sem uso (03:30) | `/etc/cron.d/marceloimob` |

Para publicar uma nova versão (envia o código, instala dependências, aplica
as migrações e reinicia):

```bash
./deploy.sh
```

A chave `key-aws.pem` nunca vai para o git (`*.pem` no `.gitignore`).
O app de gestão aponta para o servidor com
`flutter build web --dart-define=API_URL=http://18.191.168.173`.

## App Flutter

O app usa `http://localhost:8000` por padrão. Para outro endereço:

```bash
flutter run -d chrome --dart-define=API_URL=https://api.seudominio.com.br
```

Hoje o CRM, a Administração de Locação, a Administração de Vendas, a
Todos os módulos do app usam a API. Sem `--dart-define=API_URL`, o app usa
`http://localhost:8000`.

## Testes

```bash
.venv/bin/python -m pytest
```

Os testes usam um SQLite em memória descartável; não tocam no MySQL.

## Convenções da API

- Prefixo `/api/v1/<módulo>/...` (ex.: `/api/v1/crm/imoveis`).
- JSON em **camelCase**, com os mesmos nomes de campos das entidades Dart.
- Enums trafegam pelo **nome usado no Dart** (`"casaCondominio"`, `"locacao"`).
  `GET /api/v1/crm/catalogos` devolve todos com o rótulo em português.
- O `id` é um UUID gerado pelo app. `PUT /{id}` grava o registro inteiro
  (listas incluídas): atualiza se existe, cria (201) se não existe — repetir a
  mesma gravação nunca duplica. `POST` também cria (id gerado pelo servidor).
  `codigo`, `criadoEm` e `atualizadoEm` são sempre do servidor.
- Listagens são paginadas: `?limite=100&deslocamento=0` →
  `{"itens": [...], "total": n, "limite": 100, "deslocamento": 0}`.
- Autenticação: `POST /api/v1/auth/entrar` devolve um token; envie
  `Authorization: Bearer <token>` nas demais rotas. Sair, desativar o usuário,
  encerrar a sessão ou ficar inativo além do configurado invalida o token (401).
- Permissões por módulo, conforme o perfil do usuário: GET exige "ver",
  PUT/POST "criar" ou "editar", DELETE "excluir" (403 quando falta).
  Temporada usa a permissão de Locação; Manutenção, a de Locação ou Vendas.
- Erros: `{"detail": "mensagem"}` — 422 para regra de negócio/validação,
  404 para registro inexistente.
- Datas e horas sem fuso, no horário de Brasília (`2026-10-20T09:30:00`).

## Rotas – Cadastros e CRM

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/v1/crm/imoveis` | Lista (`busca`, `finalidade`, `status`, `tipo`, `cidade`, `proprietarioId`) |
| POST | `/api/v1/crm/imoveis` | Cadastra; gera o código `IM-0001`, `IM-0002`... |
| GET / PUT / DELETE | `/api/v1/crm/imoveis/{id}` | Detalhe, gravação (cria ou edita), exclusão (desvincula a agenda) |
| GET | `/api/v1/crm/contatos` | Lista (`busca`, `papel`, `etapa`, `origem`, `comPerfil`) |
| POST | `/api/v1/crm/contatos` | Cadastra (com perfil de interesse opcional) |
| GET / PUT / DELETE | `/api/v1/crm/contatos/{id}` | Detalhe, edição, exclusão (desvincula imóveis e agenda) |
| GET | `/api/v1/crm/eventos` | Agenda (`contatoId`, `imovelId`, `tipo`, `concluido`, `de`, `ate`) |
| GET | `/api/v1/crm/eventos/pendentes` | Atrasados ou de hoje, não concluídos (sino) |
| POST | `/api/v1/crm/eventos` | Novo item da Central de Relacionamento |
| GET / PUT / DELETE | `/api/v1/crm/eventos/{id}` | Detalhe, edição, exclusão |
| POST | `/api/v1/crm/eventos/{id}/alternar-conclusao` | Marca/desmarca como concluído |
| GET | `/api/v1/crm/cruzamento/contatos/{id}` | Imóveis compatíveis com o perfil do contato |
| GET | `/api/v1/crm/cruzamento/imoveis/{id}` | Contatos interessados no imóvel |
| GET | `/api/v1/crm/cruzamento/resumo` | Total de sugestões (dashboard) |
| GET | `/api/v1/crm/catalogos` | Opções dos formulários (enums, comodidades, UFs...) |

## Rotas – Administração de Locação

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/v1/locacao/contratos` | Lista (`status`, `imovelId`, `locatarioId`, `busca`) |
| GET / PUT / DELETE | `/api/v1/locacao/contratos/{id}` | Detalhe, gravação (numera `LOC-0001`...), exclusão com despesas, cobranças e repasses |
| GET | `/api/v1/locacao/despesas` | Lista (`contratoId`) |
| PUT / DELETE | `/api/v1/locacao/despesas/{id}` | Gravação e exclusão |
| GET | `/api/v1/locacao/cobrancas` | Lista (`contratoId`, `competencia`, `status`) |
| GET / PUT / DELETE | `/api/v1/locacao/cobrancas/{id}` | Cobrança com itens, pagamento e encargos (uma por contrato/mês) |
| GET | `/api/v1/locacao/repasses` | Repasses feitos (`cobrancaId`) |
| PUT / DELETE | `/api/v1/locacao/repasses/{cobrancaId}/{contatoId}` | Marca (`{"data": ...}`) ou desmarca o repasse |

A geração das cobranças do mês, encargos, valores de repasse e IR são
calculados no app; o servidor valida e guarda. Imóveis e contatos usados em
contratos não podem ser excluídos (HTTP 409).

## Rotas – Administração de Vendas

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/v1/vendas` | Lista (`status`, `imovelId`, `busca`) |
| GET / PUT / DELETE | `/api/v1/vendas/{id}` | Venda com compradores, vendedores, plano e divisão da comissão (numera `VEN-0001`...); exclusão leva as parcelas |
| DELETE | `/api/v1/vendas/{id}/parcelas` | Apaga as parcelas (antes de gerar nova tabela) |
| GET | `/api/v1/vendas/parcelas` | Parcelas (`vendaId`, `status`) |
| PUT | `/api/v1/vendas/parcelas` | Grava a tabela inteira de uma vez (lista com `id`) |
| PUT | `/api/v1/vendas/parcelas/{id}` | Grava uma parcela (ex.: pagamento) |

A tabela Price/SAC e os encargos são calculados no app. Com parcela paga, o
servidor recusa mudar as condições de pagamento da venda.

## Rotas – Locação por Temporada

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/v1/temporada/reservas` | Lista (`imovelId`, `situacao`, `de`, `ate`) |
| GET / PUT / DELETE | `/api/v1/temporada/reservas/{id}` | Reserva ou bloqueio (numera `RES-0001`...) |
| GET | `/api/v1/temporada/disponibilidade` | Reservas que impedem o período (`imovelId`, `checkIn`, `checkOut`, `ignorarId`) |

O servidor recusa reserva sobreposta a outra ativa do mesmo imóvel, mesmo que
o app de outro usuário ainda não a conheça. O período é [check-in, check-out):
um hóspede pode entrar no dia em que o anterior sai.

## Rotas – Financeiro

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/v1/financeiro/contas-bancarias` | Contas bancárias |
| PUT / DELETE | `/api/v1/financeiro/contas-bancarias/{id}` | Gravação; exclusão recusada se houver movimentação |
| GET | `/api/v1/financeiro/lancamentos` | Contas a pagar/receber (`tipo`, `status`, `contatoId`, `de`, `ate`) |
| PUT | `/api/v1/financeiro/lancamentos` | Grava várias de uma vez (repetição mensal) |
| GET / PUT / DELETE | `/api/v1/financeiro/lancamentos/{id}` | Conta com baixa/estorno; exclusão recusada se baixada ou com boleto emitido |
| GET | `/api/v1/financeiro/extrato` | Extrato (`contaId`, `de`, `ate`) |
| PUT / DELETE | `/api/v1/financeiro/extrato/{id}` | Linha do extrato; com `lancamentoId`, concilia (valor deve bater) |
| GET | `/api/v1/financeiro/boletos` | Boletos (`status`, `lancamentoId`) |
| PUT | `/api/v1/financeiro/boletos/{id}` | Emite (nosso número vazio = próximo da conta) ou atualiza |
| GET / PUT | `/api/v1/financeiro/indices` | Variações mensais dos índices (PUT substitui o mês) |
| DELETE | `/api/v1/financeiro/indices/{indice}/{ano}/{mes}` | Remove a variação |
| GET / PUT | `/api/v1/financeiro/configuracao` | Multa, juros e índice padrão |

Encargos, atualização monetária, fluxo de caixa e leitura do arquivo de
retorno são calculados no app; o servidor valida e guarda.

## Rotas – Fiscal

| Método | Rota | Descrição |
|---|---|---|
| GET / PUT | `/api/v1/fiscal/declarante` | Declarante da DIMOB (CNPJ/CPF validados pelos dígitos) |

## Rotas – Contratos e Relatórios

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/v1/contratos/modelos` | Meus modelos (`tipo`) |
| GET / PUT / DELETE | `/api/v1/contratos/modelos/{id}` | Modelo com texto e parâmetros; mantém ao menos um de locação e um de venda |

Se o servidor ainda não tem modelo de locação ou de venda, o app grava uma
cópia do modelo pronto correspondente (usado na impressão dos contratos).

## Rotas – Login e Equipe e Segurança

| Método | Rota | Descrição |
|---|---|---|
| POST | `/api/v1/auth/entrar` | Usuário e senha (`{"usuario", "senha"}`) → token; o usuário não diferencia maiúsculas |
| POST | `/api/v1/auth/sair` | Encerra a sessão atual |
| GET | `/api/v1/auth/eu` | Usuário logado |
| POST | `/api/v1/auth/alterar-senha` | Troca a própria senha |
| GET | `/api/v1/equipe/usuarios` | Equipe (todos os logados; sem senha) |
| PUT / DELETE | `/api/v1/equipe/usuarios/{id}` | Gerenciar usuários (permissão especial); `login` único, e-mail opcional, senha mín. 8 caracteres |
| GET / DELETE | `/api/v1/equipe/sessoes[/{id}]` | Conexões ativas / desconectar |
| GET / PUT | `/api/v1/equipe/configuracao` | Limite de simultâneos e inatividade |
| GET / PUT | `/api/v1/equipe/atividades[/{id}]` | Histórico (o autor vem do login) |
| GET / PUT | `/api/v1/equipe/fila` | Fila de atendimento (substitui a lista) |
| GET / PUT | `/api/v1/equipe/atendimentos[/{id}]` | Atendimentos |
| GET / PUT | `/api/v1/equipe/comissoes/regras[/{usuarioId}]` | Percentuais e metas |
| GET / PUT / DELETE | `/api/v1/equipe/comissoes[/{id}]` | Comissões (sem "ver de todos", só as próprias) |
| GET / PUT / DELETE | `/api/v1/equipe/mensagens[/{id}]` | Chat (só as conversas de que o usuário participa) |

## Rotas – Personalização

| Método | Rota | Descrição |
|---|---|---|
| GET / PUT | `/api/v1/personalizacao/empresa` | Nome, atividade, CRECI, CNPJ/CPF, endereço, contatos e chave PIX |
| GET / PUT / DELETE | `/api/v1/personalizacao/logo` | Logotipo em base64 (PNG ou JPG, até 2 MB); DELETE volta ao padrão |

Leitura liberada a todos os usuários logados (qualquer um imprime documentos);
gravar exige a permissão de Personalização. O app aplica esses dados no
cabeçalho de contratos, boletos, recibos, repasses, carnês e relatórios, e nos
campos `{{empresa_...}}` dos modelos de contrato.

## Rotas – Arquivos (fotos, vídeos e documentos)

| Método | Rota | Descrição |
|---|---|---|
| POST | `/api/v1/arquivos` | Envio multipart (`arquivo` + `categoria`: foto, video ou arquivo) |
| POST | `/api/v1/arquivos/links` | Links assinados para vários ids de uma vez |
| GET | `/api/v1/arquivos/{id}` | Dados do arquivo (nome, tipo, tamanho) e link |
| GET | `/api/v1/arquivos/{id}/conteudo?expira=…&assinatura=…` | Abre/baixa pelo link assinado (sem token; vídeos com avanço) |

Limites: fotos até 15 MB (JPG, PNG, WEBP, GIF), vídeos até 300 MB (MP4, MOV,
WEBM) e arquivos até 30 MB (PDF, Office, TXT, CSV, ZIP, DWG e imagens). Enviar
exige gravar em Cadastros e CRM. O conteúdo fica na pasta `ARQUIVOS_DIR`
(padrão `dados/arquivos`, fora do git) — inclua essa pasta no backup do
servidor. No imóvel, o anexo guarda `arquivo:<id>` no lugar do link; os links
assinados valem pelo tempo do login (`TOKEN_HORAS`).

Arquivos que nenhum imóvel usa mais (anexo removido ou imóvel excluído) são
apagados com `.venv/bin/python gerenciar.py limpar-arquivos` (ex.: cron
diário). Atrás de um proxy (nginx), libere uploads grandes:
`client_max_body_size 300m;`.

## Site público (leads e atendimento)

O próprio servidor hospeda o site da imobiliária, sem login:

| Página | O que mostra |
|---|---|
| `/` | Busca, imóveis em destaque, "Quem somos", anuncie e contato |
| `/imoveis` | Listagem com filtros (finalidade, tipo, bairro/cidade/código, quartos, valor) |
| `/imovel/{codigo}` | Fotos, vídeos, características e formulário de interesse/visita + WhatsApp |
| `/anuncie`, `/contato` | Formulários de captação e de contato |
| `/sitemap.xml`, `/robots.txt` | Para o Google |

Aparecem só os imóveis marcados como **Publicar no site** e com status
disponível; nunca dados internos (proprietário, observações, matrícula,
chaves, complemento). Endereço completo só se "Exibir endereço" estiver ligado.
Fotos e vídeos enviados ficam públicos apenas enquanto o imóvel estiver
publicado (`/midia/{id}`); documentos nunca.

Cada formulário enviado vira um **lead**: cria (ou reaproveita, pelo e-mail
ou telefone) o contato no CRM com origem "Site", cria tarefa de retorno na
Central de Relacionamento e entrega ao próximo corretor disponível da fila
(atendimento com origem "Site"). Proteções: consentimento LGPD obrigatório,
campo-isca contra robôs e limite de 5 envios a cada 10 minutos por endereço.

Textos, contatos, redes, funcionalidades (busca, destaques, valores, visita,
WhatsApp...) e a distribuição dos leads são editados no app em **Site e
Leads**. Em produção, defina `SITE_URL` (ex.: `https://www.seudominio.com.br`)
para o sitemap e aponte o domínio para este servidor.

| Método | Rota | Descrição |
|---|---|---|
| GET / PUT | `/api/v1/site/configuracao` | Configuração do site |
| GET | `/api/v1/site/leads?status=` | Leads recebidos (mais recentes primeiro) |
| PUT / DELETE | `/api/v1/site/leads/{id}` | Status, responsável e anotação / excluir |

## Área do inquilino (`/inquilino`)

Portal do locatário dentro do site, com login pelo CPF/CNPJ do contrato e
senha liberada pela equipe (Locação › Portal do inquilino no app; senha
provisória com troca obrigatória no 1º acesso; bloqueio de 15 min após 5
tentativas erradas; sessão em cookie HttpOnly de 8 h; formulários com CSRF).

| Página | O que mostra (sempre do contrato do próprio inquilino) |
|---|---|
| `/inquilino` | Resumo: em aberto, próximo vencimento, pago no ano, boletos, chamados e avisos |
| `/inquilino/pagamentos` | Valores em aberto, vencimentos (com estimativa de multa/juros) e histórico por ano |
| `/inquilino/boleto/{id}` | Boleto imprimível com PIX copia e cola; recibo quando pago |
| `/inquilino/documentos` | Via digital do contrato, laudo de vistoria e documentos; envio de fotos/vídeos do imóvel |
| `/inquilino/chamados` | Abertura de chamados de manutenção com fotos/vídeos e acompanhamento |
| `/inquilino/avisos` | Comunicados da imobiliária e avisos automáticos |

Sincronização com o sistema principal: boletos e pagamentos vêm das
cobranças da Locação; chamados viram itens da pauta de Manutenção ligados
ao contrato (origem "Inquilino"), com tarefa na Central de Relacionamento;
mudar o status na gestão avisa o inquilino; publicar um documento também.

| Método | Rota (app, permissão Locação) | Descrição |
|---|---|---|
| GET | `/api/v1/portal-inquilino/acessos` | Acessos dos inquilinos |
| POST / DELETE | `/api/v1/portal-inquilino/acessos/{contatoId}` | Libera (devolve a senha provisória uma vez) / revoga |
| GET | `/api/v1/portal-inquilino/arquivos?contratoId=&manutencaoId=` | Documentos e mídias do contrato/chamado |
| PUT / DELETE | `/api/v1/portal-inquilino/arquivos/{id}` | Publica/edita (visível ou não) / remove documento |
| GET / POST | `/api/v1/portal-inquilino/comunicados` | Avisos (sem contrato = todos os inquilinos) |
| DELETE | `/api/v1/portal-inquilino/comunicados/{id}` | Remove aviso |

## Rotas – Manutenção

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/v1/manutencoes` | Pauta (`contexto` = locacao/venda, `imovelId`, `status`) |
| GET / PUT / DELETE | `/api/v1/manutencoes/{id}` | Pauta com o diário completo (cada registro com `id`) |

## Estrutura

```
main.py                      inicia o servidor (python main.py)
app/
  main.py                    cria a aplicação, CORS, rotas de saúde
  core/                      infraestrutura comum a todos os módulos
    config.py                configurações (.env)
    database.py              conexão MySQL e sessão por requisição
    errors.py                RegraNegocio (422) / NaoEncontrado (404)
    schemas.py               base camelCase e paginação
    enums.py                 enums com rótulo
    sequencias.py            numeração sequencial (códigos, nº de contrato)
  modules/
    __init__.py              registro dos módulos
    crm/
      enums.py  catalogos.py
      models.py              tabelas
      schemas.py             contratos da API
      mapeamento.py          tabela <-> schema
      repositories.py        consultas
      services.py            regras de negócio
      cruzamento.py          pontuação do cruzamento de perfil
      api/                   rotas
migrations/                  Alembic (versions/ = histórico do banco)
tests/                       pytest, um diretório por módulo
```

## Adicionando um módulo (ex.: Administração de Locação)

1. Crie `app/modules/locacao/` copiando a divisão do `crm`.
2. Em `app/modules/__init__.py`, importe os models em `carregar_models()` e
   inclua o router em `roteadores()`.
3. Gere e aplique a migração:
   ```bash
   .venv/bin/alembic revision --autogenerate -m "locacao"
   .venv/bin/alembic upgrade head
   ```
4. Escreva os testes em `tests/locacao/`.

Todos os módulos do app já estão integrados.

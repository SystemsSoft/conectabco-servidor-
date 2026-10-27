# Servidor – Gestão Imobiliária (várias imobiliárias)

API em **Python + FastAPI** que alimenta o front-end Flutter (`marceloimob_gestao`).
Banco: **MySQL 8.4 no AWS Lightsail** (us-east-1; SQLAlchemy 2 + migrações Alembic).

O mesmo servidor atende **várias imobiliárias**: todas usam as mesmas regras
de negócio (o código de `app/modules`), mas cada uma tem o **seu banco de
dados**, a sua pasta de arquivos, os seus usuários e o seu site. Veja
[Várias imobiliárias](#várias-imobiliárias).

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

## Várias imobiliárias

```
banco central (conectabco_central)      imobiliarias: slug, nome, banco, site, ativa,
                                                      chave (ULID dos arquivos)
                                        dominios:     domínio -> imobiliária
imob_marcelo, imob_<slug>, ...          um banco por imobiliária (mesmas tabelas)
s3://associacao-conecta/imobiliarias/<ULID>/   arquivos enviados de cada uma
```

Cada requisição diz de qual imobiliária é, nesta ordem:

1. cabeçalho **`X-Imobiliaria: <slug>`** — o app de gestão;
2. parâmetro **`?imob=<slug>`** — os links assinados (arquivos, relatório e
   QR codes das auditorias) já saem com ele, pois o navegador não manda o
   cabeçalho;
3. **domínio** acessado (`Host`) — o site público e os portais do inquilino e
   do proprietário de cada imobiliária;
4. `IMOBILIARIA_PADRAO` do `.env`, se definida.

Sem identificação a API responde 400; slug ou domínio de imobiliária
desconhecida ou desativada, 404. Tokens de login e links são assinados com
uma chave própria de cada imobiliária (derivada do `JWT_SECRET`), e a sessão
fica no banco dela: o login de uma nunca vale em outra. A imobiliária padrão
continua com a chave original, então logins, links e QR codes emitidos antes
do multi-imobiliária seguem valendo.

### Painel da plataforma (`/plataforma`)

Sistema web, no próprio servidor, para cadastrar e manter as imobiliárias:
**https://api.xn--associaoconectabci-7sb3f.com.br/plataforma**. Cada
imobiliária é um "módulo" da plataforma, com:

- **banco próprio** no servidor MySQL (`imob_<slug>`), criado com todas as
  tabelas no cadastro — as regras de negócio são as mesmas para todas;
- **domínios** (site e portais), com a situação do DNS e o comando do HTTPS;
- **paleta de cores** (principal e destaque), aplicada ao site, portais,
  relatórios e entregue ao app em `GET /api/v1/marca` (público);
- **logotipo** (o mesmo da Personalização no app e dos documentos);
- **administrador** que entra no app (criar ou redefinir a senha) e
  ativar/desativar a imobiliária.

Quem entra no painel são os administradores da plataforma (banco central),
separados dos usuários das imobiliárias. Crie o primeiro no servidor:

```bash
ssh -i key_aws.pem ec2-user@44.223.83.147
cd /opt/marceloimob && sudo -u marceloimob .venv/bin/python gerenciar.py plataforma criar-admin
```

O painel não abre pelos domínios das imobiliárias, só pelo endereço do
servidor; tem bloqueio após 5 senhas erradas, sessão de 8 h e proteção CSRF.

#### Representantes e solicitações de implantação

Os **representantes** da associação entram na **área do representante**,
**https://api.xn--associaoconectabci-7sb3f.com.br/representante** (link
"Área do representante" no site institucional), com usuário e senha, e
cadastram os corretores para implantação: nome, CPF/CNPJ (conferido), CRECI,
e-mail, telefone/WhatsApp, imobiliária, cidade/UF e, se houver, domínio,
número de imóveis, contratos e usuários e observações. Lá acompanham a
situação de cada um e a resposta da associação.

No painel:

- **Nova imobiliária** fica em Solicitações: o botão cadastra o corretor (os
  mesmos campos da área do representante) como uma solicitação "cadastrada no
  painel", que segue o mesmo fluxo até o **Implantar**.
- **Solicitações** (`/plataforma/solicitacoes`, com o número de novas na aba):
  os dados do corretor e o contato do representante (e-mail e WhatsApp),
  filtros por situação (nova, em implantação, implantada, recusada), troca da
  situação com uma resposta ao representante e o botão **Implantar**, que
  abre a nova imobiliária já preenchida e, ao criá-la, marca a solicitação
  como implantada.
- **Representantes** (`/plataforma/representantes`): cadastro (nome, e-mail,
  telefone, região, usuário e senha), edição, nova senha e ativar/desativar —
  trocar a senha ou desativar encerra as sessões dele.

O login do representante segue as regras do painel (bloqueio após 5 senhas
erradas, sessão de 8 h, CSRF) com um cookie próprio: um login não abre a
área do outro. Ficam no banco central (`representantes` e
`solicitacoes_implantacao`).

#### Infraestrutura (`/plataforma/infraestrutura`)

Aba só de leitura com:

- **gasto na AWS** do mês (por serviço, a conta inteira), do mês passado e a
  previsão do fechamento (Cost Explorer, em dólar);
- **servidor**: a instância do Lightsail `AssociacaoServer` (estado, IP, plano
  e preço, CPU, crédito de burst, falhas de status) e, lidos na própria
  máquina, carga, memória, swap, disco e se `marceloimob` e `nginx` rodam;
- **banco**: o banco do Lightsail `AssociacaoDatabase` (estado, plano e preço,
  CPU, conexões, memória livre, armazenamento, backup) e o tamanho de cada
  banco MySQL, com a imobiliária dona;
- **bucket S3** `associacao-conecta`: tamanho e número de arquivos (métrica
  diária do CloudWatch).

Só esses recursos são consultados — os nomes ficam no `.env`
(`LIGHTSAIL_INSTANCIA`, `LIGHTSAIL_BANCO`, `AWS_BUCKET`, região em
`AWS_REGIAO`, padrão `us-east-1`). O que vem da AWS fica guardado em
`dados/infraestrutura.json` (`INFRA_CACHE`): o gasto por 12 h (cada consulta
ao Cost Explorer custa US$ 0,01), o Lightsail por 5 min e o bucket por 1 h. O
botão **Atualizar** consulta tudo de novo, no máximo a cada 10 min.

O Lightsail não aceita role IAM: as credenciais são de um **usuário IAM só de
leitura**, com a chave no `.env` do servidor. No console da AWS:

1. **Billing → Cost Explorer**: abra uma vez para ativar (os dados aparecem
   em até 24 h).
2. **IAM → Users → Create user** (ex.: `painel-plataforma`, sem acesso ao
   console), com esta política inline:
   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {"Effect": "Allow", "Resource": "*",
        "Action": ["ce:GetCostAndUsage", "ce:GetCostForecast", "cloudwatch:GetMetricStatistics",
                   "lightsail:GetInstance", "lightsail:GetInstanceMetricData", "lightsail:GetBundles",
                   "lightsail:GetRelationalDatabase", "lightsail:GetRelationalDatabaseMetricData",
                   "lightsail:GetRelationalDatabaseBundles"]},
       {"Effect": "Allow", "Resource": "arn:aws:s3:::associacao-conecta",
        "Action": "s3:GetBucketLocation"}
     ]
   }
   ```
3. No usuário, **Security credentials → Create access key** (*Application
   running outside AWS*) e, no `.env` do servidor:
   ```bash
   AWS_ACCESS_KEY_ID=AKIA...
   AWS_SECRET_ACCESS_KEY=...
   ```
   e `sudo systemctl restart marceloimob`.

A política só permite leitura (nenhuma ação altera ou apaga recursos); o
painel consulta apenas a instância e o banco com os nomes do `.env`.

Sem a chave, cada bloco da AWS mostra o que falta; a máquina e os bancos
MySQL aparecem do mesmo jeito. Os identificadores `nova`, `entrar`, `sair` e
`infraestrutura` são reservados (não podem virar imobiliária).

### App de gestão em cada domínio (`/gestao`)

O servidor publica o app de gestão (Flutter web, repositório
`gestao_imobiliaria`) em `/gestao` de todos os endereços: em
`https://joaoimoveis.com.br/gestao/` ele já abre como a João (nome, cores e
logotipo de `GET /api/v1/marca`, que informa o identificador e a `origem`
— `dominio`, `cabecalho`, `parametro` ou `padrao`). Fora do domínio de uma
imobiliária, o app pede o código dela. O manifesto (app instalado no
celular) sai com o nome e a cor dela. O `deploy.sh` gera o build a partir de
`../gestao` (`SEM_APP=1` publica só o servidor) para a pasta `web_gestao/`.

### Pela linha de comando

O mesmo cadastro também é mantido pelo `gerenciar.py` (o servidor relê o
cadastro a cada 30 s, sem reiniciar):

```bash
# cria o banco imob_<slug>, aplica as migrações e pede o administrador
.venv/bin/python gerenciar.py imobiliaria criar --slug joao --nome "João Imóveis" \
    --dominio joaoimoveis.com.br
.venv/bin/python gerenciar.py imobiliaria listar
.venv/bin/python gerenciar.py imobiliaria dominio joao --adicionar joao.inovacloud.app
.venv/bin/python gerenciar.py imobiliaria editar joao --site-url https://joaoimoveis.com.br
.venv/bin/python gerenciar.py imobiliaria desativar joao      # dados ficam no banco
.venv/bin/python gerenciar.py migrar                          # central + todas
```

`--site-url` é o endereço público do site (sitemap, QR codes, cookie seguro);
sem ele, vale o primeiro domínio. Domínios com `www.` não precisam de cadastro
à parte: `www.joaoimoveis.com.br` abre a imobiliária de `joaoimoveis.com.br`.

## Instalação

```bash
python3 -m venv .venv          # o PyCharm já criou a .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env .env           # preencha usuário, senha e nome do banco
```

### Banco no Lightsail

1. No console do Lightsail, em **Networking** do banco, ative o **modo público**
   (ou rode o servidor numa instância Lightsail na mesma região).
2. No `.env`, informe `DB_HOST`, `DB_USER` e `DB_PASSWORD` (o usuário precisa
   poder criar bancos: o `gerenciar.py` cria o central e o de cada
   imobiliária) e, se quiser outro nome, `DB_CENTRAL` (padrão
   `conectabco_central`).
3. (Recomendado) baixe o certificado da região e informe em `DB_SSL_CA`:
   `https://truststore.pki.rds.amazonaws.com/us-east-1/us-east-1-bundle.pem`
4. Cadastre a primeira imobiliária (cria o banco central, o dela e as tabelas):
   ```bash
   .venv/bin/python gerenciar.py imobiliaria criar --slug marcelo --nome "Marcelo Bonifácio"
   ```

Teste a conexão em `GET /saude/banco` (com `X-Imobiliaria`, testa também o
banco da imobiliária).

Para desenvolver sem MySQL, use SQLite: `CENTRAL_DATABASE_URL=sqlite:///dados/central.db`
e `DATABASE_URL=sqlite:///dados/{banco}.db` (`{banco}` vira o banco de cada
imobiliária). No SQLite o banco novo nasce direto dos models.

## Primeiro acesso (login)

Toda a API exige login. No `.env`, defina `JWT_SECRET` (chave longa e secreta
que assina os tokens; sem ela, todos precisam entrar de novo a cada reinício):

```bash
python -c "import secrets;print(secrets.token_urlsafe(48))"
```

O `imobiliaria criar` já pede o administrador. Para criar outro ou redefinir
a senha dele (pede nome, usuário de login — ex.: Marcelo — e senha):

```bash
.venv/bin/python gerenciar.py criar-admin --imobiliaria marcelo
```

Os demais usuários são criados no app, em Equipe e Segurança > Usuários.

## Rodando

```bash
.venv/bin/python main.py       # http://localhost:8000
```

Documentação interativa (Swagger): **http://localhost:8000/docs**

## Produção (AWS EC2)

Servidor **https://api.xn--associaoconectabci-7sb3f.com.br** — `api.associaçãoconectabci.com.br` (IP `44.223.83.147`, Amazon Linux
2023, usuário SSH `ec2-user`). Acessos por HTTP ou pelo IP são
redirecionados para o domínio com HTTPS.

| O quê | Onde |
|---|---|
| Código e `.env` (dono `marceloimob`, permissão 600) | `/opt/marceloimob` |
| Fotos, vídeos e arquivos enviados (uma subpasta por imobiliária) | `/var/lib/marceloimob/arquivos/<slug>` |
| Serviço (uvicorn, 2 workers, 127.0.0.1:8000) | `systemctl status marceloimob` · `journalctl -u marceloimob -f` |
| nginx: rotas para o serviço (uploads até 300 MB) | `/etc/nginx/snippets/marceloimob-proxy.conf` |
| nginx: domínio + HTTPS (gerido pelo certbot) | `/etc/nginx/conf.d/api.xn--associaoconectabci-7sb3f.com.br.conf` |
| nginx: IP/HTTP → `https://api.xn--associaoconectabci-7sb3f.com.br` | `/etc/nginx/default.d/redireciona-dominio.conf` |
| Certificado Let's Encrypt (renova sozinho) | `certbot-renew.timer` · teste: `sudo certbot renew --dry-run` |
| Limpeza diária de arquivos sem uso (03:30), de todas as imobiliárias | `/etc/cron.d/marceloimob` |

Instância nova (Amazon Linux 2023, vazia): prepare uma vez — Python 3.12,
usuário `marceloimob`, pastas, `.venv`, serviços, nginx, cron e swap — e
envie o `.env` de produção (só se o servidor ainda não tiver um):

```bash
./provisionar.sh key_aws.pem ec2-user@44.223.83.147 caminho/do/.env-producao
```

Para publicar uma nova versão (envia o código, instala dependências, aplica
as migrações no banco central e no de todas as imobiliárias e reinicia):

```bash
./deploy.sh
```

A chave `key_aws.pem` nunca vai para o git (`*.pem` no `.gitignore`).

### Passando o servidor atual para várias imobiliárias

Uma vez, na primeira publicação desta versão (o sistema fica fora do ar entre
os passos 2 e 3, cerca de um minuto):

1. Defina a imobiliária padrão no `.env` do servidor: o banco de hoje vira o
   da imobiliária `marcelo`, e o app atual, que ainda não manda
   `X-Imobiliaria`, continua funcionando:
   ```bash
   ssh -i key_aws.pem ec2-user@44.223.83.147 \
       "printf '\nIMOBILIARIA_PADRAO=marcelo\n' | sudo tee -a /opt/marceloimob/.env"
   ```
2. Publique: `./deploy.sh` (cria o banco central).
3. No servidor (`cd /opt/marceloimob`), registre o banco que já existe (o
   `DB_NAME` de hoje) e passe os arquivos para a subpasta da imobiliária:
   ```bash
   sudo -u marceloimob .venv/bin/python gerenciar.py imobiliaria criar \
       --slug marcelo --nome "Marcelo Bonifácio" --banco marceloimob --existente
   cd /var/lib/marceloimob/arquivos && sudo -u marceloimob mkdir -p marcelo && \
       sudo -u marceloimob find . -mindepth 1 -maxdepth 1 ! -name marcelo -exec mv {} marcelo/ \;
   ```

Logins, links e QR codes já emitidos continuam valendo. `DB_NAME` deixa de
ser usado (o banco de cada imobiliária fica no cadastro). Para o site de cada
imobiliária abrir pelo domínio dela, o nginx precisa repassar o domínio
acessado (`proxy_set_header Host $host;` no snippet).

### Domínio e HTTPS

O domínio está registrado na Hostinger, mas o **DNS é gerenciado pela
Netlify** (nameservers `dnsN.p01.nsone.net`): os registros ficam em
app.netlify.com → Domains → DNS settings. Registro **A** `api` →
`44.223.83.147`; a porta 443 está liberada no Security Group da EC2. Por
causa do "ç" e do "ã", use sempre a forma `xn--` do domínio
(`api.xn--associaoconectabci-7sb3f.com.br`). O HTTPS foi configurado com:

```bash
./configurar_https.sh            # e-mail opcional como 1º argumento
```

O script confere antes se o DNS já aponta para o servidor e pode ser repetido
sem efeito colateral. O certificado renova sozinho (`certbot-renew.timer`).

Domínio do site de uma imobiliária (registro **A** apontando para o servidor):
o 5º argumento é o slug dela — o domínio é cadastrado para a imobiliária e o
`SITE_URL` do servidor não muda:

```bash
./configurar_https.sh "" key_aws.pem ec2-user@44.223.83.147 joaoimoveis.com.br joao
```

## App Flutter

O app de gestão deve usar `https://api.xn--associaoconectabci-7sb3f.com.br` (`API_URL`, padrão em
`lib/core/api/api_config.dart`; o app ainda aponta para o servidor antigo,
`https://api.inovacloud.app`). Para o servidor local:

```bash
flutter run -d chrome --dart-define=API_URL=http://localhost:8000
```

Publicando o app web em outro endereço (ex.: `https://gestao.inovacloud.app`),
inclua esse endereço em `CORS_ORIGINS` no `.env`.

O app deve mandar o cabeçalho `X-Imobiliaria: <slug>` em toda chamada à API
(e manter o token por imobiliária). Enquanto não manda, as chamadas vão para
a `IMOBILIARIA_PADRAO`.

## Testes

```bash
.venv/bin/python -m pytest
```

Os testes usam SQLite em memória descartável (um banco central e um por
imobiliária); não tocam no MySQL. `tests/imobiliarias` cobre o isolamento
entre imobiliárias.

## Convenções da API

- Prefixo `/api/v1/<módulo>/...` (ex.: `/api/v1/crm/imoveis`).
- Cabeçalho `X-Imobiliaria: <slug>` em todas as rotas (ver
  [Várias imobiliárias](#várias-imobiliárias)); sem ele, 400.
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
exige gravar em Cadastros e CRM. No imóvel, o anexo guarda `arquivo:<id>` no
lugar do link; os links assinados valem pelo tempo do login (`TOKEN_HORAS`).

### Armazenamento no S3

O conteúdo fica no bucket **`associacao-conecta`** (`AWS_BUCKET`), privado,
com chaves **ULID** — únicas e em ordem de criação:

```
imobiliarias/<ULID da imobiliária>/<foto|video|arquivo>/<ULID do arquivo>
imobiliarias/<ULID da imobiliária>/miniaturas/<ULID do arquivo>-<320|640|1280>.jpg
```

- O ULID da imobiliária (`chave` no banco central) é criado no cadastro, é
  único e nunca muda — nem se o slug mudar. Cada arquivo guarda a sua chave
  (`arquivos.chave`, também única) e o objeto leva nos metadados a
  imobiliária (ULID e slug), o id do arquivo e a categoria.
- Antes de abrir, copiar ou apagar, o servidor confere se a chave está sob o
  prefixo da imobiliária da requisição; se não estiver, responde 404, não
  apaga nada e registra o erro no log (`armazenamento`).
- O link do app (`/conteudo?expira=…&assinatura=…`) confere a assinatura e
  **redireciona** (307) para um link assinado do S3 de 6 h: o S3 entrega o
  conteúdo, inclusive o avanço dos vídeos, e o servidor não carrega os bytes.
- O envio passa por `ARQUIVOS_DIR/.envios` (no disco, não na memória) só
  enquanto é conferido; a transcrição dos vídeos baixa o vídeo ali e apaga
  depois.

Em desenvolvimento e nos testes, `ARQUIVOS_ARMAZENAMENTO=disco` (padrão)
grava as mesmas chaves na pasta `ARQUIVOS_DIR` (padrão `dados/arquivos`).
O logotipo de cada imobiliária continua no banco dela (Personalização).

**Produção** — no `.env` do servidor, além das chaves da AWS:

```bash
ARQUIVOS_ARMAZENAMENTO=s3
```

O usuário IAM do servidor precisa desta política (além da do painel, em
[Infraestrutura](#infraestrutura-plataformainfraestrutura)):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {"Effect": "Allow", "Resource": "arn:aws:s3:::associacao-conecta/imobiliarias/*",
     "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"]},
    {"Effect": "Allow", "Resource": "arn:aws:s3:::associacao-conecta",
     "Action": ["s3:GetBucketLocation", "s3:ListBucket"]}
  ]
}
```

E, no bucket, **Permissions → Cross-origin resource sharing (CORS)**, para o
app web (Flutter) exibir as fotos vindas do S3:

```json
[{"AllowedOrigins": ["*"], "AllowedMethods": ["GET", "HEAD"], "AllowedHeaders": ["*"],
  "ExposeHeaders": ["Content-Length", "Content-Range", "Accept-Ranges"], "MaxAgeSeconds": 3600}]
```

(`*` é seguro aqui: o bucket continua privado e só abre por link assinado.)
Deixe ligado o **Block all public access** do bucket.

Os arquivos de antes do S3 (na pasta `ARQUIVOS_DIR/<slug>`) continuam
abrindo até serem levados ao bucket:

```bash
sudo -u marceloimob .venv/bin/python gerenciar.py migrar-arquivos
```

O comando pode ser repetido (só leva os que faltam) e não apaga a pasta
antiga — confira no app e apague depois (`dados/arquivos/<slug>`).

Arquivos que nenhum imóvel usa mais (anexo removido ou imóvel excluído) são
apagados com `.venv/bin/python gerenciar.py limpar-arquivos`, em todas as
imobiliárias (ex.: cron diário; `--imobiliaria <slug>` limpa só uma). Atrás de um proxy (nginx), libere uploads grandes:
`client_max_body_size 300m;`.

## Site público (leads e atendimento)

O próprio servidor hospeda o site de cada imobiliária, sem login, aberto
pelo domínio dela (cadastrado com `gerenciar.py imobiliaria dominio`):

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
Leads**. O endereço do site de cada imobiliária (`--site-url` no cadastro;
sem ele, `SITE_URL` do `.env`, hoje `https://api.xn--associaoconectabci-7sb3f.com.br`) define o
sitemap e os QR codes e liga o cookie seguro das áreas do inquilino e do
proprietário.

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

## Auditorias (app, permissão Auditorias)

Acompanhamento dos imóveis administrados para os proprietários:

- **Pendências automáticas** (sem cadastro manual): repasse atrasado, aluguel
  em atraso, cobrança do mês não gerada, contrato vencido/vencendo, reajuste,
  falta de garantia/fiador, laudo de vistoria e via digital, chamado sem
  resposta, manutenção parada, imóvel nunca auditado ou com auditoria antiga,
  cadastro do proprietário incompleto (CPF/CNPJ, PIX/conta). Prazos em
  `/auditorias/configuracao`.
- **Auditoria em campo**: checklist (modelos editáveis), fotos e **vídeos**,
  nota de 1 a 5, resumo e recomendações. Itens com problema viram pautas de
  Manutenção. Concluída fica travada (reabrir exige poder excluir).
- **Transcrição dos vídeos** no próprio servidor (faster-whisper, CPU): o que
  foi dito no vídeo entra no relatório e na Área do proprietário.
- **Relatório** imprimível (link assinado temporário) e publicação na Área
  do proprietário.

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/v1/auditorias/pendencias?proprietarioId=` | Pendências calculadas na hora |
| GET | `/api/v1/auditorias/proprietarios` | Saúde por proprietário (verde/amarelo/vermelho) e acesso ao portal |
| GET / PUT | `/api/v1/auditorias/configuracao` | Prazos das pendências |
| POST / DELETE | `/api/v1/auditorias/proprietarios/{contatoId}/acesso` | Libera (senha provisória mostrada uma vez) / revoga a Área do proprietário |
| GET · PUT / DELETE | `/api/v1/auditorias/modelos` · `/{id}` | Modelos de checklist |
| GET | `/api/v1/auditorias?status=&imovelId=&proprietarioId=` | Lista |
| GET / PUT / DELETE | `/api/v1/auditorias/{id}` | Auditoria com itens e mídias |
| POST | `/api/v1/auditorias/{id}/concluir` · `/reabrir` · `/publicacao` | Conclui (e publica) / reabre / publica ou retira |
| POST | `/api/v1/auditorias/{id}/manutencoes` | Gera pautas de Manutenção dos itens com problema |
| POST | `/api/v1/auditorias/{id}/relatorio` | Link temporário do relatório |
| PUT / DELETE | `/api/v1/auditorias/{id}/midias/{midiaId}` | Foto/vídeo (`referencia` = `arquivo:<id>` do upload) |
| POST | `/api/v1/auditorias/{id}/midias/{midiaId}/transcrever` | Põe o vídeo na fila de transcrição |

### Fila de transcrição

A transcrição roda num processo separado (não trava a API):

```bash
pip install -r requirements-transcricao.txt
python gerenciar.py transcrever          # fica rodando, atende a fila de todas as imobiliárias
                                         # (no servidor: serviço marceloimob-transcricao)
python gerenciar.py transcrever --uma-vez
```

`.env`: `TRANSCRICAO_MODELO` (`small` padrão; `base` é mais leve e rápido) e
`TRANSCRICAO_THREADS` (2). O modelo é baixado na 1ª vez (cache em `HF_HOME`).

## Área do proprietário (`/proprietario`)

Mesmo esquema de acesso da Área do inquilino (login pelo CPF/CNPJ, senha
liberada em Auditorias › Proprietários no app). Pode ser desligada em Site
(`mostrarAreaProprietario`).

| Página | O que mostra (só dos contratos em que ele é beneficiário) |
|---|---|
| `/proprietario` | Resumo: contratos ativos, recebido no ano, a repassar, últimas auditorias, manutenções |
| `/proprietario/repasses` | Repasses por competência (aluguel, taxas, despesas, IRRF e líquido) |
| `/proprietario/auditorias` | Auditorias publicadas: checklist, fotos, vídeos e transcrição |
| `/proprietario/manutencoes` | Manutenções dos seus imóveis |

## Integração Sicoob (testes no Sandbox)

Menu **Integração Sicoob** no app (permissão Financeiro). Usa o Sandbox do
portal developers.sicoob.com.br (client_id + token de teste): nada é cobrado
nem movimentado. A produção exige conta da imobiliária no Sicoob e o
certificado digital da empresa, e ainda não está habilitada.

| API Sicoob | Endereço (Sandbox) | O que o sistema faz |
|---|---|---|
| Cobrança Bancária v3 | `/cobranca-bancaria/v3/boletos` | Registrar boleto (com Pix), consultar, segunda via em PDF, baixar |
| Pix Recebimentos v2 | `/pix/api/v2/cob`, `/pix` | Cobrança imediata com QR code/copia e cola, consultar, Pix recebidos |
| Conta Corrente v4 | `/conta-corrente/v4/saldo`, `/v4/extrato/{mes}/{ano}` | Saldo, extrato e importação para a Conciliação bancária |

Cada requisição fica registrada (sem o token) em `/api/v1/integracoes/sicoob/chamadas`.

**Retorno de cobrança (sem API):** `POST /api/v1/integracoes/sicoob/retorno`
recebe o arquivo CNAB 240 baixado no internet banking (`conteudo` em base64).
Com `aplicar=false` devolve a prévia; com `aplicar=true` marca como pagas as
cobranças do aluguel dos boletos liquidados (movimentos 06 e 17), pelo nosso
número. Pagamento menor que a cobrança, boleto desconhecido ou cobrança
cancelada não são baixados (ficam para conferir). Reenviar o mesmo arquivo
não paga de novo.

**Situação atual:** a API não é mais usada. A integração com o Sicoob é só o
botão **Abrir Sicoob** no topo do Financeiro, que abre o login do Sicoobnet
(https://ib.sicoob.com.br/sicoobnet/ib/#/login) em outra aba (o banco não
permite embutir o site). A tela Integração Sicoob saiu do menu; o código e
as rotas acima continuam, sem uso.
O token do Sandbox fica só no banco do servidor e nunca volta na API.

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
  central/                   banco central: cadastro das imobiliárias
    models.py                imobiliarias, dominios e administradores
    services.py              cadastrar, criar o banco, migrar, logotipo
    acesso.py                login do painel da plataforma
    painel.py                painel web (/plataforma) e templates/
    infraestrutura.py        aba Infraestrutura: gasto AWS, Lightsail, banco, S3
  core/                      infraestrutura comum a todos os módulos
    config.py                configurações (.env)
    imobiliarias.py          imobiliária da requisição (cabeçalho/domínio)
    database.py              um banco por imobiliária e sessão por requisição
    errors.py                RegraNegocio (422) / NaoEncontrado (404)
    schemas.py               base camelCase e paginação
    enums.py                 enums com rótulo
    sequencias.py            numeração sequencial (códigos, nº de contrato)
    armazenamento.py         arquivos no S3 (ou disco): chaves ULID por imobiliária
    ulid.py                  gerador de ULID
    aws.py                   clientes boto3 com as credenciais do .env
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
migrations/                  Alembic dos bancos das imobiliárias
migrations_central/          Alembic do banco central (alembic -n central ...)
tests/                       pytest, um diretório por módulo
```

## Adicionando um módulo (ex.: Administração de Locação)

1. Crie `app/modules/locacao/` copiando a divisão do `crm`.
2. Em `app/modules/__init__.py`, importe os models em `carregar_models()` e
   inclua o router em `roteadores()`.
3. Gere a migração comparando com o banco de uma imobiliária e aplique em
   todas:
   ```bash
   .venv/bin/alembic -x imobiliaria=marcelo revision --autogenerate -m "locacao"
   .venv/bin/python gerenciar.py migrar
   ```
4. Escreva os testes em `tests/locacao/`.

Todos os módulos do app já estão integrados.

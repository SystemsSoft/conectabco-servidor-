# Servidor – Marcelo Bonifácio Gestão Imobiliária

API em **Python + FastAPI** que alimenta o front-end Flutter (`marceloimob_gestao`).
Banco: **MySQL 8.4 no AWS Lightsail** (SQLAlchemy 2 + migrações Alembic).

Módulos prontos:
- **Cadastros e CRM** — imóveis, contatos com perfil de interesse, cruzamento
  de perfil e Central de Relacionamento.
- **Administração de Locação** — contratos, despesas, cobranças (boletos e
  recibos) e repasses.
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

## Rodando

```bash
.venv/bin/python main.py       # http://localhost:8000
```

Documentação interativa (Swagger): **http://localhost:8000/docs**

## App Flutter

O app usa `http://localhost:8000` por padrão. Para outro endereço:

```bash
flutter run -d chrome --dart-define=API_URL=https://api.seudominio.com.br
```

Hoje o CRM, a Administração de Locação e a Manutenção usam a API; os demais
módulos ainda guardam em memória.

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

Ordem sugerida: vendas → temporada → financeiro →
fiscal → contratos/relatórios → equipe (usuários, permissões e login com JWT).

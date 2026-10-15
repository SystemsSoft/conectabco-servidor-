"""Registro dos módulos (features) do servidor.

Cada módulo fica em app/modules/<nome>/ com a mesma divisão:
  enums.py        enums com rótulo (valores = nomes do front-end)
  models.py       tabelas (SQLAlchemy)
  schemas.py      contratos da API (Pydantic, JSON em camelCase)
  mapeamento.py   tabela <-> schema
  repositories.py consultas
  services.py     regras de negócio
  api/            rotas (FastAPI)

Para adicionar um módulo: crie a pasta seguindo o padrão do `crm`, importe
os models em `carregar_models()` (para as migrações) e inclua o router em
`ROTEADORES`. Depois gere a migração com o Alembic.
"""

from fastapi import APIRouter


def carregar_models() -> None:
    """Importa os models de todos os módulos para o metadata do SQLAlchemy."""
    import app.core.sequencias  # noqa: F401
    import app.modules.crm.models  # noqa: F401
    import app.modules.locacao.models  # noqa: F401
    import app.modules.manutencao.models  # noqa: F401


def roteadores() -> list[APIRouter]:
    from app.modules.crm.api import router as crm
    from app.modules.locacao.api import router as locacao
    from app.modules.manutencao.api import router as manutencao

    return [
        crm,
        locacao,
        manutencao,
        # Próximos módulos (na ordem do menu do front-end):
        # vendas, temporada, financeiro, fiscal, contratos,
        # equipe (usuários/permissões e autenticação)
    ]

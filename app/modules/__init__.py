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
    import app.modules.contratos.models  # noqa: F401
    import app.modules.crm.models  # noqa: F401
    import app.modules.financeiro.models  # noqa: F401
    import app.modules.fiscal.models  # noqa: F401
    import app.modules.locacao.models  # noqa: F401
    import app.modules.manutencao.models  # noqa: F401
    import app.modules.temporada.models  # noqa: F401
    import app.modules.vendas.models  # noqa: F401


def roteadores() -> list[APIRouter]:
    from app.modules.contratos.api import router as contratos
    from app.modules.crm.api import router as crm
    from app.modules.financeiro.api import router as financeiro
    from app.modules.fiscal.api import router as fiscal
    from app.modules.locacao.api import router as locacao
    from app.modules.manutencao.api import router as manutencao
    from app.modules.temporada.api import router as temporada
    from app.modules.vendas.api import router as vendas

    return [
        crm,
        locacao,
        manutencao,
        vendas,
        temporada,
        financeiro,
        fiscal,
        contratos,
        # Próximos módulos (na ordem do menu do front-end):
        # equipe (usuários/permissões e autenticação)
    ]

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
`roteadores()` com a permissão exigida. Depois gere a migração com o Alembic.
"""

from fastapi import APIRouter


def carregar_models() -> None:
    """Importa os models de todos os módulos para o metadata do SQLAlchemy."""
    import app.core.sequencias  # noqa: F401
    import app.modules.arquivos.models  # noqa: F401
    import app.modules.auditoria.models  # noqa: F401
    import app.modules.contratos.models  # noqa: F401
    import app.modules.crm.models  # noqa: F401
    import app.modules.equipe.models  # noqa: F401
    import app.modules.financeiro.models  # noqa: F401
    import app.modules.fiscal.models  # noqa: F401
    import app.modules.inquilino.models  # noqa: F401
    import app.modules.locacao.models  # noqa: F401
    import app.modules.manutencao.models  # noqa: F401
    import app.modules.personalizacao.models  # noqa: F401
    import app.modules.proprietario.models  # noqa: F401
    import app.modules.sicoob.models  # noqa: F401
    import app.modules.site.models  # noqa: F401
    import app.modules.temporada.models  # noqa: F401
    import app.modules.vendas.models  # noqa: F401


def roteadores() -> list[tuple[APIRouter, list]]:
    """Rotas de cada módulo com a permissão exigida (ação pelo método HTTP:
    GET = ver, PUT/POST = criar ou editar, DELETE = excluir)."""
    from app.core.auth import exigir_modulo
    from app.modules.arquivos.api import router as arquivos
    from app.modules.auditoria.api import router as auditorias
    from app.modules.contratos.api import router as contratos
    from app.modules.crm.api import router as crm
    from app.modules.equipe.api import auth
    from app.modules.equipe.api import router as equipe
    from app.modules.financeiro.api import router as financeiro
    from app.modules.fiscal.api import router as fiscal
    from app.modules.inquilino.api import router as portal_inquilino
    from app.modules.locacao.api import router as locacao
    from app.modules.manutencao.api import router as manutencao
    from app.modules.personalizacao.api import router as personalizacao
    from app.modules.sicoob.api import router as sicoob
    from app.modules.site.api import router as site
    from app.modules.temporada.api import router as temporada
    from app.modules.vendas.api import router as vendas

    return [
        (auth, []),  # login aberto; demais rotas de /auth exigem o token
        (equipe, []),  # permissões conferidas rota a rota
        (crm, [exigir_modulo("cadastrosCrm")]),
        (locacao, [exigir_modulo("locacao")]),
        (vendas, [exigir_modulo("vendas")]),
        (temporada, [exigir_modulo("locacao")]),
        (manutencao, [exigir_modulo("locacao", "vendas")]),
        (financeiro, [exigir_modulo("financeiro")]),
        (fiscal, [exigir_modulo("fiscal")]),
        (contratos, [exigir_modulo("contratosRelatorios")]),
        # Leitura liberada a todos (documentos); gravar exige Personalização.
        (personalizacao, []),
        # Enviar exige Cadastros e CRM; abrir usa link assinado.
        (arquivos, []),
        (site, [exigir_modulo("site")]),
        (portal_inquilino, [exigir_modulo("locacao")]),
        (auditorias, [exigir_modulo("auditorias")]),
        (sicoob, [exigir_modulo("financeiro")]),
    ]

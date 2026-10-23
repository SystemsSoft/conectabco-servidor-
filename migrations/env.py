"""Ambiente do Alembic dos bancos das imobiliárias (todos com as mesmas
tabelas). Aplique com `python gerenciar.py migrar` (todos os bancos) ou, em
um só: alembic -x imobiliaria=<identificador> upgrade head."""

from logging.config import fileConfig

from alembic import context

from app.core.config import get_settings
from app.core.database import Base, criar_engine
from app.modules import carregar_models

config = context.config
# Pelo gerenciar.py chega a conexão pronta (e o log dele é mantido).
conexao = config.attributes.get("connection")
if conexao is None and config.config_file_name is not None:
    fileConfig(config.config_file_name)

carregar_models()
target_metadata = Base.metadata


def _url():
    if url := config.get_main_option("sqlalchemy.url"):
        return url
    s = get_settings()
    slug = context.get_x_argument(as_dictionary=True).get("imobiliaria") or s.imobiliaria_padrao
    if not slug:
        raise SystemExit(
            "Informe a imobiliária: alembic -x imobiliaria=<identificador> upgrade head "
            "(ou rode python gerenciar.py migrar, que aplica em todas)."
        )
    from app.core.imobiliarias import buscar

    imob = buscar(slug)
    if imob is None:
        raise SystemExit(f"Imobiliária '{slug}' não cadastrada.")
    return s.url_imobiliaria(imob.banco)


def _rodar(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    """Gera o SQL sem conectar (alembic -x imobiliaria=... upgrade head --sql)."""
    url = _url()
    context.configure(
        url=url if isinstance(url, str) else url.render_as_string(hide_password=False),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    if conexao is not None:
        _rodar(conexao)
        return
    engine = criar_engine(_url())
    try:
        with engine.connect() as connection:
            _rodar(connection)
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

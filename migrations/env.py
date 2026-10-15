"""Ambiente do Alembic: usa a mesma configuração (.env) e os models da API."""

from logging.config import fileConfig

from alembic import context

from app.core.config import get_settings
from app.core.database import Base, criar_engine
from app.modules import carregar_models

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

carregar_models()
target_metadata = Base.metadata


def _url():
    return config.get_main_option("sqlalchemy.url") or get_settings().url_banco


def run_migrations_offline() -> None:
    """Gera o SQL sem conectar (alembic upgrade head --sql)."""
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
    url = config.get_main_option("sqlalchemy.url") or None
    with criar_engine(url).connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

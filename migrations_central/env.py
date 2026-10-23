"""Ambiente do Alembic do banco central (cadastro das imobiliárias).
Aplicado pelo `python gerenciar.py migrar` ou por: alembic -n central upgrade head."""

from logging.config import fileConfig

from alembic import context

import app.central.models  # noqa: F401
from app.core.config import get_settings
from app.core.database import BaseCentral, criar_engine

config = context.config
# Pelo gerenciar.py chega a conexão pronta (e o log dele é mantido).
conexao = config.attributes.get("connection")
if conexao is None and config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = BaseCentral.metadata


def _url():
    return config.get_main_option("sqlalchemy.url") or get_settings().url_central


def _rodar(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
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

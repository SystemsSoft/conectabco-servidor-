"""Conexão com o banco (MySQL em produção) e sessão por requisição."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, MetaData, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings

# Nomes previsíveis para índices e chaves (facilita as migrações).
_convencao = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=_convencao)


def criar_engine(url=None) -> Engine:
    s = get_settings()
    url = url or s.url_banco
    if str(url).startswith("sqlite"):
        return create_engine(url)
    connect_args = {"ssl": {"ca": s.db_ssl_ca}} if s.db_ssl_ca else {}
    return create_engine(
        url,
        pool_pre_ping=True,  # descarta conexões derrubadas pelo MySQL
        pool_recycle=3600,  # antes do wait_timeout padrão
        connect_args=connect_args,
    )


@lru_cache
def get_engine() -> Engine:
    return criar_engine()


@lru_cache
def _fabrica() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """Dependência do FastAPI: uma sessão por requisição."""
    with _fabrica()() as sessao:
        yield sessao

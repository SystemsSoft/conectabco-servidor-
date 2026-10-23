"""Conexões com os bancos (MySQL em produção) e sessão por requisição.

Cada imobiliária tem o seu banco, todos com as mesmas tabelas (Base); o
banco central guarda o cadastro das imobiliárias (BaseCentral)."""

import threading
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import URL, Engine, MetaData, create_engine, event, make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.core.imobiliarias import Imobiliaria, atual

# Nomes previsíveis para índices e chaves (facilita as migrações).
_convencao = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Tabelas do banco de cada imobiliária."""

    metadata = MetaData(naming_convention=_convencao)


class BaseCentral(DeclarativeBase):
    """Tabelas do banco central (cadastro das imobiliárias)."""

    metadata = MetaData(naming_convention=_convencao)


def criar_engine(url: str | URL) -> Engine:
    s = get_settings()
    if make_url(url).get_backend_name() == "sqlite":
        return _engine_sqlite(url)
    connect_args = {"ssl": {"ca": s.db_ssl_ca}} if s.db_ssl_ca else {}
    return create_engine(
        url,
        pool_pre_ping=True,  # descarta conexões derrubadas pelo MySQL
        pool_recycle=3600,  # antes do wait_timeout padrão
        pool_size=s.db_pool,
        max_overflow=s.db_pool_extra,
        connect_args=connect_args,
    )


def _engine_sqlite(url: str | URL) -> Engine:
    """SQLite (testes e desenvolvimento) com as chaves estrangeiras ligadas;
    em memória, uma conexão só, compartilhada entre as threads."""
    extra = {"poolclass": StaticPool} if make_url(url).database in (None, "", ":memory:") else {}
    engine = create_engine(url, connect_args={"check_same_thread": False}, **extra)

    @event.listens_for(engine, "connect")
    def _fks(conexao, _):
        conexao.execute("PRAGMA foreign_keys=ON")

    return engine


@lru_cache
def motor_central() -> Engine:
    return criar_engine(get_settings().url_central)


# Um engine (e um pool de conexões) por banco de imobiliária, criado no
# primeiro uso.
_motores: dict[str, tuple[Engine, sessionmaker[Session]]] = {}
_trava = threading.Lock()


def _do_banco(banco: str) -> tuple[Engine, sessionmaker[Session]]:
    with _trava:
        if banco not in _motores:
            engine = criar_engine(get_settings().url_imobiliaria(banco))
            _motores[banco] = (engine, sessionmaker(bind=engine, expire_on_commit=False))
        return _motores[banco]


def motor(imobiliaria: Imobiliaria | None = None) -> Engine:
    """Engine do banco da imobiliária (a da requisição, se nenhuma for dada)."""
    return _do_banco((imobiliaria or atual()).banco)[0]


def fabrica(imobiliaria: Imobiliaria | None = None) -> sessionmaker[Session]:
    """Fábrica de sessões do banco da imobiliária (a da requisição, se
    nenhuma for dada)."""
    return _do_banco((imobiliaria or atual()).banco)[1]


def descartar_motores() -> None:
    """Fecha as conexões de todos os bancos (testes; troca de configuração)."""
    with _trava:
        for engine, _ in _motores.values():
            engine.dispose()
        _motores.clear()
    if motor_central.cache_info().currsize:
        motor_central().dispose()
    motor_central.cache_clear()


def get_db() -> Iterator[Session]:
    """Dependência do FastAPI: uma sessão por requisição, no banco da
    imobiliária da requisição."""
    with fabrica()() as sessao:
        yield sessao

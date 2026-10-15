"""Os testes usam um SQLite em memória, criado e descartado a cada teste;
a aplicação em si usa o MySQL configurado no .env."""

from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import create_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    engine = sa.create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @sa.event.listens_for(engine, "connect")
    def _fks(conexao, _):
        conexao.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    fabrica = sessionmaker(bind=engine, expire_on_commit=False)

    def _db() -> Iterator[Session]:
        with fabrica() as s:
            yield s

    app = create_app()
    app.dependency_overrides[get_db] = _db
    with TestClient(app) as c:
        yield c
    engine.dispose()

"""Os testes usam um SQLite em memória, criado e descartado a cada teste;
a aplicação em si usa o MySQL configurado no .env. O `client` já está logado
como administrador; `cliente_anonimo` não tem token."""

from collections.abc import Iterator

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.main import create_app

ADMIN = {"usuario": "Admin", "senha": "senha-forte-123"}


@pytest.fixture
def banco():
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
    with fabrica() as db:
        from app.modules.equipe.services import criar_administrador

        criar_administrador(db, "Administrador", ADMIN["usuario"], ADMIN["senha"])
    yield fabrica
    engine.dispose()


@pytest.fixture
def cliente_anonimo(banco) -> Iterator[TestClient]:
    def _db() -> Iterator[Session]:
        with banco() as s:
            yield s

    app = create_app()
    app.dependency_overrides[get_db] = _db
    with TestClient(app) as c:
        yield c


@pytest.fixture
def client(cliente_anonimo) -> TestClient:
    r = cliente_anonimo.post("/api/v1/auth/entrar", json=ADMIN)
    assert r.status_code == 200, r.text
    cliente_anonimo.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return cliente_anonimo

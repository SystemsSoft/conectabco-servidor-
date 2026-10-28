"""Os testes usam SQLite em memória (um banco central e um por imobiliária),
criados e descartados a cada teste; a aplicação em si usa o MySQL configurado
no .env. Durante o teste a imobiliária "teste" é a atual (`imobiliaria`); o
`client` já está logado como administrador dela; `cliente_anonimo` não tem
token. `nova_imobiliaria` cadastra outras (testes de isolamento)."""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.central import services as central
from app.core import imobiliarias
from app.core.config import get_settings
from app.core.database import Base, BaseCentral, descartar_motores, fabrica, motor, motor_central
from app.core.imobiliarias import Imobiliaria, usar
from app.main import create_app

ADMIN = {"usuario": "Admin", "senha": "senha-forte-123"}


@pytest.fixture(autouse=True)
def sem_caixa_de_email_real(monkeypatch):
    """Nenhum teste lê nem envia pela caixa de e-mail configurada no .env local."""
    s = get_settings()
    monkeypatch.setattr(s, "email_usuario", "")
    monkeypatch.setattr(s, "email_senha", "")


@pytest.fixture
def plataforma(monkeypatch, tmp_path) -> Iterator[None]:
    s = get_settings()
    for campo, valor in {
        "central_database_url": "sqlite://",
        "database_url": "sqlite://",
        "imobiliaria_padrao": "",
        "site_url": "",
        "arquivos_dir": str(tmp_path / "arquivos"),
        # Nunca o S3 nem o redirecionamento do .env local.
        "arquivos_armazenamento": "disco",
        "site_principal_url": "",
    }.items():
        monkeypatch.setattr(s, campo, valor)
    descartar_motores()
    imobiliarias.limpar_cadastro()
    BaseCentral.metadata.create_all(motor_central())
    yield
    descartar_motores()
    imobiliarias.limpar_cadastro()


def criar_imobiliaria(slug: str, nome: str, dominios: tuple[str, ...] = ()) -> Imobiliaria:
    """Cadastro + tabelas (create_all, sem as migrações) + administrador."""
    from app.modules.equipe.services import criar_administrador

    with central.sessao() as db:
        imob = central.validar_nova(db, slug, nome, dominios=dominios)
        central.registrar(db, imob)
    Base.metadata.create_all(motor(imob))
    with usar(imob), fabrica(imob)() as db:
        criar_administrador(db, "Administrador", ADMIN["usuario"], ADMIN["senha"])
    return imob


@pytest.fixture
def nova_imobiliaria(plataforma):
    return criar_imobiliaria


@pytest.fixture
def imobiliaria(plataforma) -> Iterator[Imobiliaria]:
    imob = criar_imobiliaria("teste", "Imobiliária Teste")
    with usar(imob):
        yield imob


@pytest.fixture
def banco(imobiliaria):
    """Fábrica de sessões do banco da imobiliária do teste."""
    return fabrica(imobiliaria)


@pytest.fixture
def cliente_anonimo(banco, imobiliaria) -> Iterator[TestClient]:
    with TestClient(create_app(), headers={imobiliarias.CABECALHO: imobiliaria.slug}) as c:
        yield c


@pytest.fixture
def client(cliente_anonimo) -> TestClient:
    r = cliente_anonimo.post("/api/v1/auth/entrar", json=ADMIN)
    assert r.status_code == 200, r.text
    cliente_anonimo.headers["Authorization"] = f"Bearer {r.json()['token']}"
    return cliente_anonimo

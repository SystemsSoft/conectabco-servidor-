"""Várias imobiliárias no mesmo servidor: cada uma só enxerga o próprio banco,
os próprios arquivos e os próprios logins."""

from pathlib import Path

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from app.central import services as central
from app.core import imobiliarias
from app.core.config import get_settings
from app.core.database import descartar_motores, fabrica, motor
from app.core.errors import RegraNegocio
from app.core.imobiliarias import normalizar_dominio, usar
from app.core.seguranca import _segredo, chave
from app.main import create_app
from app.modules.personalizacao.models import DadosEmpresa
from tests.apoio import contato
from tests.conftest import ADMIN

CONTATOS = "/api/v1/crm/contatos"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


@pytest.fixture
def outra(nova_imobiliaria):
    return nova_imobiliaria("outra", "Outra Imobiliária", dominios=("outra.com.br",))


@pytest.fixture
def servidor(imobiliaria) -> TestClient:
    """Cliente sem o cabeçalho X-Imobiliaria."""
    with TestClient(create_app()) as c:
        yield c


def _entrar(c: TestClient, **cabecalhos) -> dict:
    r = c.post("/api/v1/auth/entrar", json=ADMIN, headers=cabecalhos)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"} | cabecalhos


def test_cada_imobiliaria_ve_so_o_proprio_banco(client, outra):
    contato(client, "Cliente da Teste")
    da_outra = _entrar(client, **{"X-Imobiliaria": "outra"})
    assert client.get(CONTATOS).json()["total"] == 1
    assert client.get(CONTATOS, headers=da_outra).json()["total"] == 0
    contato(client.__class__(client.app, headers=da_outra), "Cliente da Outra")
    assert [c["nome"] for c in client.get(CONTATOS).json()["itens"]] == ["Cliente da Teste"]

    # O login de uma imobiliária não vale na outra.
    r = client.get(CONTATOS, headers={"X-Imobiliaria": "outra"})
    assert r.status_code == 401
    # Documentos saem com o nome do cadastro de cada uma.
    assert client.get("/api/v1/personalizacao/empresa", headers=da_outra).json()["nome"] == (
        "Outra Imobiliária")  # fmt: skip


def test_identificacao_da_imobiliaria(servidor, outra, monkeypatch):
    r = servidor.post("/api/v1/auth/entrar", json=ADMIN)
    assert r.status_code == 400 and "X-Imobiliaria" in r.json()["detail"]
    assert servidor.get("/saude").status_code == 200
    r = servidor.post("/api/v1/auth/entrar", json=ADMIN, headers={"X-Imobiliaria": "nenhuma"})
    assert (r.status_code, r.json()["detail"]) == (404, "Imobiliária não encontrada.")

    # Pelo parâmetro (links abertos no navegador) e pelo domínio (site e portais).
    assert servidor.post("/api/v1/auth/entrar?imob=outra", json=ADMIN).status_code == 200
    for host in ("outra.com.br", "www.outra.com.br", "OUTRA.com.br:443"):
        token = _entrar(servidor, host=host)
        assert servidor.get(CONTATOS, headers=token).status_code == 200
        assert servidor.get(CONTATOS, headers=token | {"X-Imobiliaria": "teste"}).status_code == 401
    assert servidor.get("/saude/banco", headers={"host": "outra.com.br"}).json()["imobiliaria"] == "outra"

    # Sem identificação, vale a imobiliária padrão do .env.
    monkeypatch.setattr(get_settings(), "imobiliaria_padrao", "teste")
    token = _entrar(servidor)
    assert servidor.get(CONTATOS, headers=token).status_code == 200

    # Desativada, deixa de abrir (os dados ficam no banco).
    with central.sessao() as db:
        central.definir_ativa(db, "outra", False)
    assert servidor.post("/api/v1/auth/entrar", json=ADMIN, headers={"host": "outra.com.br"}).status_code == 404
    assert servidor.post("/api/v1/auth/entrar?imob=outra", json=ADMIN).status_code == 404


def test_arquivos_e_links_de_cada_imobiliaria(client, servidor, outra):
    def enviar(cabecalhos=None):
        r = client.post("/api/v1/arquivos", data={"categoria": "foto"},
                        files={"arquivo": ("f.png", PNG, "image/png")}, headers=cabecalhos)  # fmt: skip
        assert r.status_code == 201, r.text
        return r.json()

    pasta = Path(get_settings().arquivos_dir)
    da_teste = enviar()
    da_outra = enviar(_entrar(client, **{"X-Imobiliaria": "outra"}))
    assert (pasta / "teste" / da_teste["id"][:2] / da_teste["id"]).is_file()
    assert (pasta / "outra" / da_outra["id"][:2] / da_outra["id"]).is_file()

    # O link assinado diz a imobiliária: abre no navegador, sem cabeçalho.
    assert "imob=teste" in da_teste["link"]
    assert servidor.get(da_teste["link"]).content == PNG
    assert servidor.get(da_teste["link"].replace("imob=teste", "imob=outra")).status_code == 404
    assert servidor.get(da_outra["link"]).content == PNG


def test_chave_de_assinatura_por_imobiliaria(outra, imobiliaria, monkeypatch):
    with usar(outra):
        da_outra = chave()
    assert chave() != da_outra and _segredo() not in (chave(), da_outra)
    # A padrão segue com a chave de antes (logins e QR codes já emitidos).
    monkeypatch.setattr(get_settings(), "imobiliaria_padrao", "teste")
    assert chave() == _segredo()


def test_validacoes_do_cadastro(outra):
    with central.sessao() as db:
        for dados, erro in (
            (("Ruim!", "X"), "Identificador inválido"),
            (("outra", "X"), "Já existe"),
            (("nova", " "), "Informe o nome"),
            (("nova", "X", "imob_outra"), "já é de outra imobiliária"),
            (("nova", "X", "", "ftp://x"), "Endereço do site inválido"),
            (("nova", "X", "", "", ["www.Outra.com.br"]), None),
            (("nova", "X", "", "", ["https://outra.com.br/"]), "já é da imobiliária 'outra'"),
            (("nova", "X", "", "", ["dominio inválido"]), "Domínio inválido"),
        ):
            if erro is None:
                assert central.validar_nova(db, *dados).dominios == ("www.outra.com.br",)
                continue
            with pytest.raises(RegraNegocio, match=erro):
                central.validar_nova(db, *dados)
        central.adicionar_dominio(db, "outra", "outra.localhost")
    assert normalizar_dominio("https://WWW.Exemplo.com.br.:8443/x") == "www.exemplo.com.br"
    assert imobiliarias.buscar("outra").dominios == ("outra.com.br", "outra.localhost")


def test_criar_imobiliaria_com_banco_proprio(plataforma, tmp_path, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "central_database_url", f"sqlite:///{tmp_path}/central.db")
    monkeypatch.setattr(s, "database_url", f"sqlite:///{tmp_path}/{{banco}}.db")
    descartar_motores()

    imob = central.criar_imobiliaria("nova-imob", "Nova Imobiliária", dominios=["nova.com.br"])
    assert (imob.banco, imob.site_url) == ("imob_nova_imob", "https://nova.com.br")
    assert (tmp_path / "imob_nova_imob.db").is_file() and imob.pasta_arquivos.is_dir()
    assert imobiliarias.buscar("nova-imob") == imob
    with fabrica(imob)() as db:
        assert db.get(DadosEmpresa, 1).nome == "Nova Imobiliária"
    with motor(imob).connect() as c:
        assert c.scalar(sa.text("SELECT version_num FROM alembic_version"))

    # Banco que já existe só com --existente (ex.: o da primeira imobiliária).
    (tmp_path / "legado.db").touch()
    with pytest.raises(RegraNegocio, match="já existe"):
        central.criar_imobiliaria("legado", "Legado", banco="legado")
    assert imobiliarias.buscar("legado") is None
    assert central.criar_imobiliaria("legado", "Legado", banco="legado", existente=True).ativa


def test_url_do_servidor_mysql_sem_o_banco():
    url = get_settings()._url_mysql("conectabco_central")
    assert central.url_servidor(url).database is None
    assert central.url_servidor(url).host == url.host

"""App de gestão (Flutter web) em /gestao: arquivos do build, rotas do app e
manifesto com a marca da imobiliária do domínio."""

import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


@pytest.fixture
def app_web(imobiliaria, nova_imobiliaria, tmp_path, monkeypatch) -> TestClient:
    pasta = tmp_path / "web"
    pasta.mkdir()
    (pasta / "index.html").write_text("<html>app</html>")
    (pasta / "main.dart.js").write_text("// app")
    (pasta / "manifest.json").write_text(json.dumps({"name": "Gestão Imobiliária", "short_name": "Gestão",
                                                     "theme_color": "#020B22"}))  # fmt: skip
    (tmp_path / "segredo.txt").write_text("não pode sair")
    monkeypatch.setattr(get_settings(), "gestao_web_dir", str(pasta))
    nova_imobiliaria("maria", "Maria Imóveis Planejados", dominios=("mariaimoveis.com.br",))
    with TestClient(create_app(), follow_redirects=False) as c:
        yield c


def test_serve_o_build_e_as_rotas_do_app(app_web):
    assert app_web.get("/gestao").headers["location"] == "/gestao/"
    inicio = app_web.get("/gestao/")
    assert inicio.text == "<html>app</html>" and inicio.headers["cache-control"] == "no-cache"
    assert app_web.get("/gestao/main.dart.js").headers["cache-control"].startswith("public")
    assert app_web.get("/gestao/login").text == "<html>app</html>"  # rota do app
    assert app_web.get("/gestao/nao-existe.js").status_code == 404
    assert "não pode sair" not in app_web.get("/gestao/..%2fsegredo.txt").text


def test_manifesto_com_a_marca_do_dominio(app_web):
    padrao = app_web.get("/gestao/manifest.json").json()
    assert padrao["name"] == "Gestão Imobiliária"
    maria = app_web.get("/gestao/manifest.json", headers={"host": "mariaimoveis.com.br"}).json()
    assert (maria["name"], maria["short_name"]) == ("Maria Imóveis Planejados", "Maria")


def test_sem_build_publicado(imobiliaria, tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "gestao_web_dir", str(tmp_path / "vazio"))
    with TestClient(create_app()) as c:
        assert c.get("/gestao/").status_code == 404

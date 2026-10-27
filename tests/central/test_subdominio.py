"""Imobiliária sem domínio próprio: subdomínio personalizado no domínio da
associação (ex.: lima.associaçãoconectabci.com.br)."""

import pytest

from app.central import services as central
from app.core import imobiliarias
from app.core.config import get_settings
from app.core.errors import RegraNegocio
from tests.central.test_painel import _entrar, _nova, painel  # noqa: F401 - fixture

BASE = "xn--associaoconectabci-7sb3f.com.br"


@pytest.fixture
def associacao(monkeypatch):
    monkeypatch.setattr(get_settings(), "site_principal_url", f"https://{BASE}/")


def test_nome_do_subdominio(associacao):
    assert central.subdominio_da_associacao("Lima Imóveis") == f"lima-imoveis.{BASE}"
    assert central.subdominio_da_associacao("  joao2 ") == f"joao2.{BASE}"
    assert central.exibir_dominio(f"joao2.{BASE}") == "joao2.associaçãoconectabci.com.br"
    for nome, erro in (("ab", "inválido"), ("", "inválido"), ("api", "reservado"), ("www", "reservado"),
                       ("x" * 41, "inválido")):  # fmt: skip
        with pytest.raises(RegraNegocio, match=erro):
            central.subdominio_da_associacao(nome)


def test_sem_dominio_da_associacao_configurado(monkeypatch):
    monkeypatch.setattr(get_settings(), "site_principal_url", "")
    monkeypatch.setattr(get_settings(), "subdominio_base", "")
    with pytest.raises(RegraNegocio, match="não está configurado"):
        central.subdominio_da_associacao("lima")


def test_cadastro_com_subdominio_da_associacao(painel, associacao):  # noqa: F811
    csrf = _entrar(painel)
    form = painel.get("/plataforma/nova").text
    assert "Subdomínio da associação" in form and ".associaçãoconectabci.com.br" in form

    r = _nova(painel, csrf, tipo_dominio="associacao", subdominio="api")
    assert r.status_code == 422 and "reservado" in r.text and 'value="associacao" checked' in r.text
    r = _nova(painel, csrf, tipo_dominio="associacao", subdominio="João Imóveis", dominios="ignorado.com.br")
    assert r.headers["location"] == "/plataforma/joao?msg=criada"
    imobiliarias.limpar_cadastro()
    imob = imobiliarias.buscar("joao")
    assert imob.dominios == (f"joao-imoveis.{BASE}",) and imob.site_url == f"https://joao-imoveis.{BASE}"
    # Abre pelo subdomínio (como pelo domínio próprio) e não pode ser usado por outra.
    assert painel.get("/api/v1/marca", headers={"host": f"joao-imoveis.{BASE}"}).json()["nome"] == "João Imóveis"
    r = _nova(painel, csrf, slug="outra", tipo_dominio="associacao", subdominio="joao-imoveis")
    assert r.status_code == 422 and "já é da imobiliária &#39;joao&#39;" in r.text


def test_dominio_proprio_continua_igual(painel, associacao):  # noqa: F811
    csrf = _entrar(painel)
    assert _nova(painel, csrf, tipo_dominio="proprio", subdominio="lixo").status_code == 303
    imobiliarias.limpar_cadastro()
    assert imobiliarias.buscar("joao").dominios == ("joaoimoveis.com.br",)


def test_pagina_mostra_https_automatico_no_subdominio(painel, associacao):  # noqa: F811
    csrf = _entrar(painel)
    _nova(painel, csrf, tipo_dominio="associacao", subdominio="lima")
    painel.post("/plataforma/joao/dominios", data={"csrf": csrf, "dominio": "limaimoveis.com.br"})
    pagina = painel.get("/plataforma/joao").text
    assert "lima.associaçãoconectabci.com.br" in pagina and "HTTPS automático" in pagina
    # O domínio próprio continua com o passo a passo do HTTPS; o subdomínio, não.
    assert pagina.count("Como ligar este domínio") == 1 and "configurar_https.sh" in pagina
    assert f"configurar_https.sh \"\" key_aws.pem ec2-user@" in pagina and f"lima.{BASE} joao" not in pagina

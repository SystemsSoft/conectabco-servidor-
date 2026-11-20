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
    assert r.status_code == 422 and "joao-imoveis.associaçãoconectabci.com.br já é usado por outra imobiliária" in r.text


def test_dominio_proprio_continua_igual(painel, associacao):  # noqa: F811
    csrf = _entrar(painel)
    assert _nova(painel, csrf, tipo_dominio="proprio", subdominio="lixo").status_code == 303
    imobiliarias.limpar_cadastro()
    assert imobiliarias.buscar("joao").dominios == ("joaoimoveis.com.br",)


IP = "32.192.43.203"


def _no_servidor(monkeypatch, dns: bool, https: bool):
    """Como se o painel rodasse no servidor (com IP), com o DNS e o HTTPS
    de todos os nomes no estado pedido (sem rede nem nginx de verdade)."""
    from app.central import painel as p

    monkeypatch.setattr(p, "_ip_do_servidor", lambda request: IP)
    monkeypatch.setattr(p, "_aponta", lambda dominio, ip: dns)
    monkeypatch.setattr(p, "_https_ok", lambda dominio: https)


def test_pagina_mostra_o_estado_real_do_subdominio(painel, associacao):  # noqa: F811
    csrf = _entrar(painel)
    _nova(painel, csrf, tipo_dominio="associacao", subdominio="lima")
    painel.post("/plataforma/joao/dominios", data={"csrf": csrf, "dominio": "limaimoveis.com.br"})
    # Fora do servidor não dá para conferir o HTTPS: sem selo, e o subdomínio
    # não promete "nada a configurar".
    pagina = painel.get("/plataforma/joao").text
    assert "lima.associaçãoconectabci.com.br" in pagina and "Nada a configurar" not in pagina
    assert "HTTPS ligado" not in pagina and "HTTPS não ligado" not in pagina
    # O domínio próprio continua com o passo a passo do HTTPS.
    assert pagina.count("Como ligar este domínio") == 1 and "configurar_https.sh" in pagina
    assert f"configurar_https.sh \"\" key_aws.pem ec2-user@" in pagina and f"lima.{BASE} joao" not in pagina
    assert "https://lima.associaçãoconectabci.com.br/gestao/" in pagina


def test_curinga_ainda_nao_ligado(painel, associacao, monkeypatch):  # noqa: F811
    _no_servidor(monkeypatch, dns=False, https=False)
    csrf = _entrar(painel)
    nova = painel.get("/plataforma/nova").text
    assert "ainda não estão ligados neste servidor" in nova and f"ec2-user@{IP}" in nova
    _nova(painel, csrf, tipo_dominio="associacao", subdominio="lima")
    pagina = painel.get("/plataforma/joao").text
    assert f"DNS ainda não aponta para {IP}" in pagina and "HTTPS não ligado" in pagina
    assert "Falta ligar os subdomínios da associação" in pagina and "Nada a configurar" not in pagina
    assert f"configurar_https_subdominios.sh \"\" key_aws.pem ec2-user@{IP}" in pagina
    assert f"apontando para <code>{IP}</code>" in pagina and 'id="aviso-curinga"' in pagina

    # Só o DNS já criado: o passo 1 aparece como feito.
    _no_servidor(monkeypatch, dns=True, https=False)
    pagina = painel.get("/plataforma/joao").text
    assert "DNS aponta para este servidor" in pagina and "HTTPS não ligado" in pagina
    assert pagina.count('<span class="selo ok">Feito</span>') == 2  # no domínio e no aviso do formulário


def test_curinga_ligado(painel, associacao, monkeypatch):  # noqa: F811
    _no_servidor(monkeypatch, dns=True, https=True)
    csrf = _entrar(painel)
    assert "ainda não estão ligados" not in painel.get("/plataforma/nova").text
    _nova(painel, csrf, tipo_dominio="associacao", subdominio="lima")
    pagina = painel.get("/plataforma/joao").text
    assert "HTTPS ligado" in pagina and "Nada a configurar" in pagina
    assert "Falta ligar" not in pagina and 'id="aviso-curinga"' not in pagina


def test_endereco_do_site_fora_dos_dominios(painel, associacao):  # noqa: F811
    csrf = _entrar(painel)
    _nova(painel, csrf, tipo_dominio="associacao", subdominio="lima")
    with central.sessao() as db:
        central.obter(db, "joao").site_url = "https://joao.netlify.app"
        db.commit()
    pagina = painel.get("/plataforma/joao").text
    assert "https://joao.netlify.app</a>, que não está entre os domínios abaixo" in pagina
    assert 'class="selo ok">Principal' not in pagina


def test_contratar_com_subdominio_e_implantar_ja_escolhido(painel, associacao):  # noqa: F811
    from app.central import models as m
    from tests.central.test_contratacao import DADOS, _iniciar, _texto
    from tests.central.test_representantes import _pagar

    form = painel.get("/contratar").text
    assert 'name="tipo_dominio"' in form and ".associaçãoconectabci.com.br" in form
    # Conferência ao vivo do nome.
    assert painel.get("/contratar/subdominio", params={"nome": "Lima Imóveis"}).json() == {
        "ok": True, "dominio": "lima-imoveis.associaçãoconectabci.com.br"}  # fmt: skip
    assert painel.get("/contratar/subdominio", params={"nome": "api"}).json()["ok"] is False

    url = _iniciar(painel, site="", tipo_dominio="associacao", subdominio="Lima Imóveis")
    assert "lima-imoveis.associaçãoconectabci.com.br" in _texto(painel.get(f"{url}/contrato.pdf").content)
    painel.post(f"{url}/assinar", data={"nome": "Joana Lima", "aceite": "on"})
    # O mesmo nome já pedido por outra solicitação em aberto é recusado.
    r = painel.post("/contratar", data=DADOS | {"tipo_dominio": "associacao", "subdominio": "lima-imoveis"})
    assert r.status_code == 422 and "já foi pedido em outra solicitação" in r.text

    with central.sessao() as db:
        (s,) = db.query(m.SolicitacaoImplantacao).all()
        assert s.dominio == f"lima-imoveis.{BASE}"
        sid = s.id
    csrf = _entrar(painel)
    _pagar(painel, csrf, sid)
    pagina = painel.get(f"/plataforma/nova?solicitacao={sid}").text
    assert 'value="associacao" checked' in pagina and 'value="lima-imoveis"' in pagina
    # Ao implantar, o próprio pedido não conta como "já pedido".
    r = _nova(painel, csrf, slug="lima", solicitacao=sid, tipo_dominio="associacao", subdominio="lima-imoveis")
    assert r.status_code == 303, r.text
    imobiliarias.limpar_cadastro()
    assert imobiliarias.buscar("lima").dominios == (f"lima-imoveis.{BASE}",)


def test_trocar_entre_dominio_proprio_e_subdominio(painel, associacao):  # noqa: F811
    csrf = _entrar(painel)
    _nova(painel, csrf)  # começa com domínio próprio
    pagina = painel.get("/plataforma/joao").text
    assert "Principal" in pagina and "Tornar principal" not in pagina

    # Próprio → subdomínio, já como principal.
    r = painel.post("/plataforma/joao/dominios",
                    data={"csrf": csrf, "tipo": "associacao", "subdominio": "joao", "principal": "1"})  # fmt: skip
    assert r.headers["location"] == "/plataforma/joao?msg=dominio-principal"
    imobiliarias.limpar_cadastro()
    imob = imobiliarias.buscar("joao")
    assert imob.site_url == f"https://joao.{BASE}" and set(imob.dominios) == {"joaoimoveis.com.br", f"joao.{BASE}"}
    assert painel.get("/plataforma/joao").text.count("Tornar principal") == 1

    # Remover o domínio próprio; depois voltar para ele (subdomínio → próprio).
    painel.post("/plataforma/joao/dominios/remover", data={"csrf": csrf, "dominio": "joaoimoveis.com.br"})
    r = painel.post("/plataforma/joao/dominios", data={"csrf": csrf, "tipo": "proprio", "dominio": "joao.com.br"})
    assert r.headers["location"] == "/plataforma/joao?msg=dominio"
    r = painel.post("/plataforma/joao/dominios/principal", data={"csrf": csrf, "dominio": "joao.com.br"})
    assert r.headers["location"] == "/plataforma/joao?msg=dominio-principal"
    imobiliarias.limpar_cadastro()
    assert imobiliarias.buscar("joao").site_url == "https://joao.com.br"

    # Removendo o principal, o que sobrar assume.
    painel.post("/plataforma/joao/dominios/remover", data={"csrf": csrf, "dominio": "joao.com.br"})
    imobiliarias.limpar_cadastro()
    assert imobiliarias.buscar("joao").site_url == f"https://joao.{BASE}"

    # Erros: subdomínio de outra imobiliária, domínio que não é dela, vazio.
    _nova(painel, csrf, slug="maria", nome="Maria", dominios="maria.com.br", admin_login="maria")
    r = painel.post("/plataforma/maria/dominios", data={"csrf": csrf, "tipo": "associacao", "subdominio": "joao"},
                    follow_redirects=True)  # fmt: skip
    assert "já é usado por outra imobiliária" in r.text
    r = painel.post("/plataforma/maria/dominios/principal", data={"csrf": csrf, "dominio": f"joao.{BASE}"},
                    follow_redirects=True)  # fmt: skip
    assert imobiliarias.buscar("maria").site_url != f"https://joao.{BASE}"
    r = painel.post("/plataforma/maria/dominios", data={"csrf": csrf, "dominio": " "}, follow_redirects=True)
    assert "Informe o domínio" in r.text

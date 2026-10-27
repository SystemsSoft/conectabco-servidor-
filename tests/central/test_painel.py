"""Painel da plataforma: login, cadastro de imobiliária (banco próprio,
domínio, cores, logotipo e administrador) e as proteções do painel."""

import re

import pytest
from fastapi.testclient import TestClient

from app.central import acesso
from app.central import services as central
from app.core import imobiliarias
from app.core.config import get_settings
from app.core.database import descartar_motores
from app.main import create_app

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
DONA = {"login": "dona", "senha": "senha-da-plataforma"}
# Contratante válido (contrato de prestação de serviços).
CONTRATO = {f"contrato_{k}": v for k, v in {
    "nome": "João da Silva", "endereco": "Rua Moreira César", "numero": "200", "bairro": "Icaraí",
    "cidade": "Niterói", "uf": "RJ", "cpf": "529.982.247-25", "identidade": "12.345.678-9",
    "creci": "12345-F RJ", "telefone_1": "(21) 98888-7777",
}.items()}  # fmt: skip


@pytest.fixture
def painel(plataforma, tmp_path, monkeypatch) -> TestClient:
    """Bancos em arquivos SQLite (o painel cria bancos de verdade)."""
    s = get_settings()
    monkeypatch.setattr(s, "central_database_url", f"sqlite:///{tmp_path}/central.db")
    monkeypatch.setattr(s, "database_url", f"sqlite:///{tmp_path}/{{banco}}.db")
    descartar_motores()
    imobiliarias.limpar_cadastro()
    central.migrar_central()
    with central.sessao() as db:
        acesso.criar_administrador(db, "Dona da Plataforma", DONA["login"], DONA["senha"])
    with TestClient(create_app(), follow_redirects=False) as c:
        yield c


def _entrar(c: TestClient) -> str:
    assert c.post("/plataforma/entrar", data=DONA).status_code == 303
    return _csrf(c.get("/plataforma").text)


def _csrf(html: str) -> str:
    return re.search(r'name="csrf" value="([^"]+)"', html).group(1)


def _nova(c: TestClient, csrf: str, **extra):
    dados = {
        "csrf": csrf, "slug": "joao", "nome": "João Imóveis", "dominios": "joaoimoveis.com.br",
        "cor_primaria": "#123456", "cor_destaque": "#ff6600",
        "admin_nome": "João", "admin_login": "joao", "admin_senha": "senha-do-joao",
    } | CONTRATO | extra  # fmt: skip
    return c.post("/plataforma/nova", data=dados, files={"logo": ("logo.png", PNG, "image/png")})


def test_login_do_painel(painel):
    assert painel.get("/plataforma").headers["location"] == "/plataforma/entrar"
    r = painel.post("/plataforma/entrar", data=DONA | {"senha": "errada"})
    assert r.status_code == 422 and "Usuário ou senha incorretos." in r.text
    for _ in range(4):
        painel.post("/plataforma/entrar", data=DONA | {"senha": "errada"})
    assert "Muitas tentativas" in painel.post("/plataforma/entrar", data=DONA).text

    with central.sessao() as db:  # nova senha desbloqueia
        acesso.criar_administrador(db, "Dona", DONA["login"], DONA["senha"])
    csrf = _entrar(painel)
    assert "Nenhuma imobiliária cadastrada" in painel.get("/plataforma").text
    # O login de uma imobiliária não abre o painel, nem o cookie sem CSRF.
    assert painel.post("/plataforma/sair").status_code == 403
    assert painel.post("/plataforma/sair", data={"csrf": csrf}).status_code == 303
    assert painel.get("/plataforma").status_code == 303


def test_cria_imobiliaria_com_banco_dominio_cores_e_logo(painel):
    csrf = _entrar(painel)
    assert _nova(painel, "x").status_code == 403
    r = _nova(painel, csrf, slug="Ruim!")
    assert r.status_code == 422 and "Identificador inválido" in r.text
    assert imobiliarias.buscar("ruim") is None

    r = _nova(painel, csrf)
    assert r.headers["location"] == "/plataforma/joao?msg=criada"
    pagina = painel.get(r.headers["location"]).text
    assert "banco, tabelas e administrador prontos" in pagina and "joaoimoveis.com.br" in pagina
    assert painel.get("/plataforma/joao/logo").content == PNG

    # O administrador entra no app pela API da imobiliária.
    app_joao = {"X-Imobiliaria": "joao"}
    login = {"usuario": "joao", "senha": "senha-do-joao"}
    assert painel.post("/api/v1/auth/entrar", json=login, headers=app_joao).status_code == 200
    marca = painel.get("/api/v1/marca", headers=app_joao).json()
    assert marca == {"imobiliaria": "joao", "origem": "cabecalho", "nome": "João Imóveis",
                     "corPrimaria": "#123456", "corDestaque": "#ff6600",
                     "temLogo": True, "logo": "/logo?imob=joao"}  # fmt: skip
    # O app aberto pelo domínio dela descobre quem é sem cabeçalho.
    pelo_dominio = painel.get("/api/v1/marca", headers={"host": "www.joaoimoveis.com.br"}).json()
    assert (pelo_dominio["imobiliaria"], pelo_dominio["origem"]) == ("joao", "dominio")
    assert painel.get("/api/v1/marca").status_code == 400  # endereço sem imobiliária
    assert painel.get(marca["logo"]).content == PNG
    # O site, pelo domínio dela, sai com a paleta dela.
    site = painel.get("/", headers={"host": "joaoimoveis.com.br"}).text
    assert "--navy-800:#123456" in site and "--gold:#ff6600" in site

    # Editar cores, domínios, administrador e situação.
    painel.post("/plataforma/joao", data={"csrf": csrf, "nome": "João Imóveis Ltda",
                                         "cor_primaria": "#061a48", "cor_destaque": "#00aa55"})  # fmt: skip
    marca = painel.get("/api/v1/marca", headers=app_joao).json()
    assert (marca["corPrimaria"], marca["corDestaque"]) == ("#061a48", "#00aa55")
    assert "--navy-800" not in painel.get("/", headers={"host": "joaoimoveis.com.br"}).text
    r = painel.post("/plataforma/joao", data={"csrf": csrf, "nome": "X", "cor_primaria": "azul"})
    assert "Cor inválida" in painel.get(r.headers["location"]).text
    painel.post("/plataforma/joao/dominios", data={"csrf": csrf, "dominio": "www.joao.imb.br"})
    assert "www.joao.imb.br" in imobiliarias.buscar("joao").dominios
    painel.post("/plataforma/joao/dominios/remover", data={"csrf": csrf, "dominio": "joaoimoveis.com.br"})
    assert "joaoimoveis.com.br" not in imobiliarias.buscar("joao").dominios
    r = painel.post("/plataforma/joao/administrador",
                    data={"csrf": csrf, "login": "joao", "senha": "nova-senha-joao"})  # fmt: skip
    assert r.headers["location"].endswith("msg=admin")
    login["senha"] = "nova-senha-joao"
    assert painel.post("/api/v1/auth/entrar", json=login, headers=app_joao).status_code == 200
    painel.post("/plataforma/joao/logo/remover", data={"csrf": csrf})
    assert painel.get("/plataforma/joao/logo").status_code == 404

    painel.post("/plataforma/joao/situacao", data={"csrf": csrf, "ativa": "0"})
    assert painel.post("/api/v1/auth/entrar", json=login, headers=app_joao).status_code == 404
    assert "Desativada" in painel.get("/plataforma").text


def test_painel_nao_abre_pelo_dominio_da_imobiliaria(painel):
    csrf = _entrar(painel)
    _nova(painel, csrf)
    assert painel.get("/plataforma", headers={"host": "joaoimoveis.com.br"}).status_code == 404
    assert painel.get("/plataforma/entrar", headers={"host": "www.joaoimoveis.com.br"}).status_code == 404
    assert "Disallow: /plataforma" in painel.get("/robots.txt").text

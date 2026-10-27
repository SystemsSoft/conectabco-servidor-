"""Contratação pelo site: dados do contratante, contrato preenchido em PDF,
assinatura eletrônica ou gov.br e o que aparece no painel depois."""

import io
from datetime import timedelta

import pytest
from pypdf import PdfReader

from app.central import comercial as com
from app.central import contratacao as cc
from app.central import models as m
from app.central import pre_cadastro
from app.central import services as central
from app.core.tempo import agora
from tests.central.test_painel import _entrar, painel  # noqa: F401 - fixture

DADOS = {"nome": "Joana Lima", "nome_comercial": "Lima Imóveis", "cpf": "529.982.247-25",
         "identidade": "12.345.678-9", "creci": "12345-F RJ", "endereco": "Rua Moreira César", "numero": "200",
         "bairro": "Icaraí", "cidade": "Niterói", "uf": "RJ", "telefone_1": "(21) 98888-7777",
         "email": "Joana@Lima.com.br", "site": "https://limaimoveis.com.br/", "instagram": "@limaimoveis",
         "lgpd": "on"}  # fmt: skip
ASSINADO_GOVBR = b"%PDF-1.7\n1 0 obj << /Type /Sig /Filter /Adobe.PPKLite /ByteRange [0 10 20 30] >> endobj\n%%EOF"


@pytest.fixture(autouse=True)
def limpar_limite():
    pre_cadastro._envios.clear()


def _iniciar(c, **extra) -> str:
    r = c.post("/contratar", data=DADOS | extra)
    assert r.status_code == 303, r.text
    return r.headers["location"]


def _texto(pdf: bytes) -> str:
    return "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages)


def test_dados_e_contrato_preenchido(painel):  # noqa: F811
    assert "Contrate o sistema imobiliário" in painel.get("/contratar").text
    r = painel.post("/contratar", data=DADOS | {"lgpd": ""})
    assert r.status_code == 422 and "LGPD" in r.text
    r = painel.post("/contratar", data=DADOS | {"cpf": "111.111.111-11"})
    assert r.status_code == 422 and "CPF inválido" in r.text and 'value="Joana Lima"' in r.text
    assert painel.post("/contratar", data=DADOS | {"email": "x"}).status_code == 422

    url = _iniciar(painel)
    pagina = painel.get(url).text
    assert "Leia e assine o contrato" in pagina and "Joana Lima" in pagina and "529.982.247-25" in pagina
    assert "assinador.iti.br" in pagina
    r = painel.get(f"{url}/contrato.pdf")
    assert r.headers["content-type"] == "application/pdf" and r.headers["content-disposition"].startswith("inline")
    texto = _texto(r.content)
    for valor in ("CONTRATO DE PRESTAÇÃO DE SERVIÇOS", "Joana Lima", "529.982.247-25", "Lima Imóveis",
                  "limaimoveis.com.br", "@limaimoveis", "Rua Moreira César"):
        assert valor in texto, valor
    assert painel.get(f"{url}/contrato.pdf?baixar=1").headers["content-disposition"].startswith("attachment")
    assert "inválido ou expirado" in painel.get("/contratar/token-que-nao-existe").text
    # O contrato em branco, para ler antes (link da landing page).
    r = painel.get("/contratar/modelo.pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert "CLÁUSULA 1ª" in _texto(r.content) and "Joana" not in _texto(r.content)


def test_assinatura_eletronica_vira_solicitacao_e_lead(painel):  # noqa: F811
    url = _iniciar(painel)
    assinar = f"{url}/assinar"
    assert "Marque que leu" in painel.post(assinar, data={"nome": "Joana Lima"}).text
    r = painel.post(assinar, data={"nome": "Outra Pessoa", "aceite": "on"})
    assert r.status_code == 422 and "exatamente como no contrato" in r.text
    r = painel.post(assinar, data={"nome": "  joana LIMA ", "aceite": "on"}, headers={"user-agent": "Teste/1.0"})
    assert r.headers["location"] == url
    pagina = painel.get(url).text
    assert "Contrato assinado!" in pagina and "Próximos passos" in pagina
    assert "já foi assinado" in painel.post(assinar, data={"nome": "Joana Lima", "aceite": "on"}).text

    via = painel.get(f"{url}/contrato.pdf")
    texto = _texto(via.content)
    assert len(PdfReader(io.BytesIO(via.content)).pages) == 7
    assert "Registro de assinatura eletrônica" in texto and "joana LIMA" in texto and "Teste/1.0" in texto

    with central.sessao() as db:
        (contrato,) = db.query(m.ContratoDigital).all()
        assert (contrato.situacao, contrato.metodo, contrato.email) == ("assinado", "eletronica", "joana@lima.com.br")
        assert len(contrato.hash_contrato) == 64 and contrato.hash_contrato in texto
        s = db.get(m.SolicitacaoImplantacao, contrato.solicitacao_id)
        assert (s.situacao, s.representante_id, s.administrador_id) == ("nova", None, None)
        assert (s.nome_imobiliaria, s.dominio, s.cpf_cnpj) == ("Lima Imóveis", "limaimoveis.com.br", "52998224725")
        (lead,) = com.leads(db, "convertido")
        assert (lead.perfil, lead.solicitacao_id) == ("Contratação online", s.id)

    # No painel: Tecnologia, Financeiro (contrato anexado) e o Implantar já preenchido.
    _entrar(painel)
    assert "Contratou pelo site" in painel.get("/plataforma/solicitacoes").text
    fin = painel.get(f"/plataforma/financeiro/{s.id}").text
    assert "Contrato assinado pelo site" in fin and "contrato-assinado.pdf" in fin and "Assinatura eletrônica" in fin
    from tests.central.test_representantes import _pagar

    assert "financeiro" in painel.get(f"/plataforma/nova?solicitacao={s.id}").headers["location"]  # sem o 1º pagamento
    csrf = fin.split('name="csrf" value="')[1].split('"')[0]
    _pagar(painel, csrf, s.id)
    form = painel.get(f"/plataforma/nova?solicitacao={s.id}").text
    for campo, valor in (("identidade", "12.345.678-9"), ("endereco", "Rua Moreira César"),
                         ("bairro", "Icaraí"), ("instagram", "@limaimoveis")):
        assert f'name="contrato_{campo}" value="{valor}"' in form, campo
    assert "Contratação pelo site" in painel.get("/plataforma/comercial/representantes?periodo=tudo").text


def test_assinatura_govbr(painel):  # noqa: F811
    url = _iniciar(painel)
    enviar = f"{url}/govbr"
    sem_assinatura = painel.post(enviar, files={"arquivo": ("c.pdf", b"%PDF-1.7 sem assinatura", "application/pdf")})
    assert sem_assinatura.status_code == 422 and "não tem assinatura digital" in sem_assinatura.text
    assert "em PDF" in painel.post(enviar, files={"arquivo": ("c.png", b"\x89PNG", "image/png")}).text
    assert painel.post(enviar, files={"arquivo": ("assinado.pdf", ASSINADO_GOVBR, "application/pdf")}).status_code == 303
    assert "Contrato assinado!" in painel.get(url).text and "(assinatura gov.br)" in painel.get(url).text
    assert painel.get(f"{url}/contrato.pdf").content == ASSINADO_GOVBR  # a via enviada, intacta
    with central.sessao() as db:
        (contrato,) = db.query(m.ContratoDigital).all()
        assert contrato.metodo == "govbr" and contrato.hash_contrato == cc.contrato_pdf.sha256(ASSINADO_GOVBR)
    _entrar(painel)
    fin = painel.get(f"/plataforma/financeiro/{contrato.solicitacao_id}").text
    assert "validar.iti.gov.br" in fin and "contrato-assinado-govbr.pdf" in fin


def test_link_expira_e_limite_de_tentativas(painel):  # noqa: F811
    url = _iniciar(painel)
    with central.sessao() as db:
        c = db.query(m.ContratoDigital).one()
        c.criado_em = agora() - cc.VALIDADE - timedelta(minutes=1)
        db.commit()
    r = painel.get(url)
    assert r.status_code == 404 and "inválido ou expirado" in r.text
    pre_cadastro._envios.clear()
    estados = [painel.post("/contratar", data=DADOS).status_code for _ in range(6)]
    assert estados == [303] * 5 + [429]


PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def test_contrato_antes_e_logotipo_ate_o_implantar(painel):  # noqa: F811
    form = painel.get("/contratar").text
    assert 'href="/contratar/modelo.pdf"' in form and "Ler o contrato antes" in form
    assert 'enctype="multipart/form-data"' in form and 'name="logo"' in form

    r = painel.post("/contratar", data=DADOS, files={"logo": ("logo.gif", b"GIF89a", "image/gif")})
    assert r.status_code == 422 and "JPG, JPEG ou PNG" in r.text
    r = painel.post("/contratar", data=DADOS, files={"logo": ("logo.png", b"nao e imagem", "image/png")})
    assert r.status_code == 422 and "PNG ou JPG" in r.text
    r = painel.post("/contratar", data=DADOS, files={"logo": ("marca.png", PNG, "image/png")})
    assert r.status_code == 303
    url = r.headers["location"]
    with central.sessao() as db:
        c = db.query(m.ContratoDigital).one()
        assert c.logo_tipo == "image/png" and c.logo_chave.startswith(f"plataforma/contratos/{c.id}/")

    painel.post(f"{url}/assinar", data={"nome": "Joana Lima", "aceite": "on"})
    with central.sessao() as db:
        s = db.get(m.SolicitacaoImplantacao, db.query(m.ContratoDigital).one().solicitacao_id)
        from app.central import financeiro as fin

        logo = fin.logo(db, s)
        assert logo.nome == "logotipo.png" and fin.conteudo(logo) == PNG

    # No Implantar, o logotipo enviado é usado se não escolherem outro.
    from tests.central.test_painel import CONTRATO
    from tests.central.test_representantes import _pagar

    csrf = _entrar(painel)
    _pagar(painel, csrf, s.id)
    assert "Logotipo enviado pelo contratante" in painel.get(f"/plataforma/nova?solicitacao={s.id}").text
    r = painel.post("/plataforma/nova", data={
        "csrf": csrf, "slug": "lima", "nome": "Lima Imóveis", "admin_nome": "Joana Lima",
        "admin_login": "joana", "admin_senha": "senha-da-joana", "solicitacao": s.id} | CONTRATO)  # fmt: skip
    assert r.headers["location"] == "/plataforma/lima?msg=criada"
    from app.core import imobiliarias

    imobiliarias.limpar_cadastro()
    assert central.logo(imobiliarias.buscar("lima")) == (PNG, "image/png")

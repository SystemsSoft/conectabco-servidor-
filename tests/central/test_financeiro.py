"""Financeiro das solicitações: painel de controle, documentos (boletos e
comprovantes) e a confirmação do 1º pagamento que libera a Tecnologia."""

from datetime import date, timedelta
from pathlib import Path

from app.core.config import get_settings
from tests.central.test_painel import _entrar, painel  # noqa: F401 - fixture
from tests.central.test_representantes import CORRETOR

PDF = b"%PDF-1.4 boleto de cobranca"


def _solicitacao(c, csrf) -> str:
    assert c.post("/plataforma/solicitacoes/nova", data=CORRETOR | {"csrf": csrf}).status_code == 303
    pagina = c.get("/plataforma/financeiro").text
    return pagina.split('href="/plataforma/financeiro/')[1].split('"')[0]


def _enviar(c, csrf, sid, nome="boleto.pdf", conteudo=PDF, tipo="boleto"):
    return c.post(f"/plataforma/financeiro/{sid}/documentos", data={"csrf": csrf, "tipo": tipo, "descricao": "Nov/2026"},
                  files={"arquivo": (nome, conteudo, "application/octet-stream")})  # fmt: skip


def test_painel_do_financeiro_e_documentos(painel):  # noqa: F811
    csrf = _entrar(painel)
    sid = _solicitacao(painel, csrf)
    lista = painel.get("/plataforma/financeiro").text
    assert "Lima Imóveis" in lista and "Aguardando 1º pagamento" in lista
    menu = lista.split('aria-label="Áreas da plataforma"')[1].split("</nav>")[0]
    assert 'Financeiro <span class="contador">1</span>' in menu

    pagina = painel.get(f"/plataforma/financeiro/{sid}").text
    for texto in ("Joana Lima", "529.982.247-25", "CRECI 12345-F RJ", "Lima Imóveis", "Cadastrada no painel"):
        assert texto in pagina, texto

    # Documentos: só PDF/JPG/PNG de verdade, com CSRF.
    assert painel.post(f"/plataforma/financeiro/{sid}/documentos", data={"tipo": "boleto"},
                       files={"arquivo": ("b.pdf", PDF)}).status_code == 403  # fmt: skip
    assert "Formato" in painel.get(_enviar(painel, csrf, sid, nome="virus.exe").headers["location"]).text
    assert "PDF%20v%C3%A1lido" in _enviar(painel, csrf, sid, conteudo=b"<html>").headers["location"]
    assert _enviar(painel, csrf, sid).headers["location"].endswith("msg=documento")
    _enviar(painel, csrf, sid, nome="pix.png", conteudo=b"\x89PNG\r\n\x1a\n" + b"0" * 50, tipo="comprovante")
    pagina = painel.get(f"/plataforma/financeiro/{sid}").text
    assert "boleto.pdf" in pagina and "pix.png" in pagina and "Comprovante de pagamento" in pagina
    doc = pagina.split('href="/plataforma/financeiro/documentos/')[1].split('"')[0]
    aberto = painel.get(f"/plataforma/financeiro/documentos/{doc}")
    assert aberto.status_code == 200 and aberto.content.startswith((PDF, b"\x89PNG"))
    assert aberto.headers["content-disposition"].startswith("inline")
    guardados = [p for p in (Path(get_settings().arquivos_dir) / "plataforma").rglob("*") if p.is_file()]
    assert len(guardados) == 2 and all(f"solicitacoes/{sid}/" in str(p) for p in guardados)

    # Só quem está logado no painel abre.
    painel.cookies.clear()
    assert painel.get(f"/plataforma/financeiro/documentos/{doc}").headers["location"] == "/plataforma/entrar"
    csrf = _entrar(painel)
    assert painel.post(f"/plataforma/financeiro/documentos/{doc}/remover", data={"csrf": csrf}).status_code == 303
    assert painel.get(f"/plataforma/financeiro/documentos/{doc}").status_code == 404
    assert len([p for p in (Path(get_settings().arquivos_dir) / "plataforma").rglob("*") if p.is_file()]) == 1


def test_primeiro_pagamento_libera_a_tecnologia(painel):  # noqa: F811
    csrf = _entrar(painel)
    sid = _solicitacao(painel, csrf)
    url = f"/plataforma/financeiro/{sid}/pagamento"
    amanha = (date.today() + timedelta(days=1)).isoformat()
    assert "futura" in painel.get(painel.post(url, data={"csrf": csrf, "data_pagamento": amanha}).headers["location"]).text
    assert "Informe a data" in painel.get(painel.post(url, data={"csrf": csrf}).headers["location"]).text
    r = painel.post(url, data={"csrf": csrf, "data_pagamento": date.today().isoformat(), "observacao": "Pix recebido"})
    assert r.headers["location"].endswith("msg=pagamento")
    pagina = painel.get(f"/plataforma/financeiro/{sid}").text
    assert "1º pagamento confirmado" in pagina and "Pix recebido" in pagina and "Dona da Plataforma" in pagina
    assert "Lima Imóveis" in painel.get("/plataforma/financeiro?filtro=pago").text
    assert "Lima Imóveis" not in painel.get("/plataforma/financeiro").text  # saiu dos que aguardam
    solicitacoes = painel.get("/plataforma/solicitacoes").text
    assert f"/plataforma/nova?solicitacao={sid}" in solicitacoes and "falta o 1º pagamento" not in solicitacoes

    # Desfazer só enquanto a Tecnologia não avançou.
    assert painel.post(f"{url}/desfazer", data={"csrf": csrf}).headers["location"].endswith("msg=pagamento-desfeito")
    painel.post(url, data={"csrf": csrf, "data_pagamento": date.today().isoformat()})
    painel.post(f"/plataforma/solicitacoes/{sid}", data={"csrf": csrf, "situacao": "em_andamento", "resposta": ""})
    r = painel.post(f"{url}/desfazer", data={"csrf": csrf})
    assert "n%C3%A3o%20pode%20ser%20desfeito" in r.headers["location"]


def test_recusada_nao_tem_pagamento(painel):  # noqa: F811
    csrf = _entrar(painel)
    sid = _solicitacao(painel, csrf)
    painel.post(f"/plataforma/solicitacoes/{sid}", data={"csrf": csrf, "situacao": "recusada", "resposta": ""})
    r = painel.post(f"/plataforma/financeiro/{sid}/pagamento",
                    data={"csrf": csrf, "data_pagamento": date.today().isoformat()})  # fmt: skip
    assert "recusada" in r.headers["location"].lower()
    assert "Lima Imóveis" not in painel.get("/plataforma/financeiro").text
    assert "Lima Imóveis" in painel.get("/plataforma/financeiro?filtro=todas").text

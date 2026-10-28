"""Caixa de e-mail da associação no painel, com IMAP e SMTP de mentira."""

import email
import re
import uuid
from email.message import EmailMessage
from email.policy import default as politica

import pytest

from app.central import emails as em
from app.central import models as m
from app.central import services as central
from app.core.config import get_settings
from app.core.tempo import agora
from tests.central.test_painel import _csrf, _entrar, painel  # noqa: F401 - fixture


def _mensagem(de="Marcos Pereira <marcos.pereira@exemplo.com>", assunto="Quero saber do sistema", texto="Olá!\nTudo bem?",
              html=None, anexo=None, mid=None) -> bytes:  # fmt: skip
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = de, "contato@xn--associaoconectabci-7sb3f.com.br", assunto
    msg["Date"] = "Wed, 28 Oct 2026 10:15:00 -0300"
    msg["Message-ID"] = mid or f"<{uuid.uuid4()}@exemplo.com>"
    msg.set_content(texto)
    if html:
        msg.add_alternative(html, subtype="html")
    if anexo:
        msg.add_attachment(anexo[1], maintype="application", subtype="pdf", filename=anexo[0])
    return msg.as_bytes()


class ImapFalso:
    def __init__(self, caixa):
        self.caixa = caixa  # {"uidvalidity": int, "mensagens": {uid: bytes}, "enviados": []}

    def select(self, pasta, readonly=False):
        assert readonly, "o painel nunca altera a caixa"
        return "OK", [str(len(self.caixa["mensagens"])).encode()]

    def response(self, codigo):
        return codigo, [str(self.caixa["uidvalidity"]).encode()]

    def uid(self, comando, *args):
        if comando == "search":
            inicio = int(re.search(r"UID (\d+):\*", args[1]).group(1))
            uids = [u for u in sorted(self.caixa["mensagens"]) if u >= inicio] or sorted(self.caixa["mensagens"])[-1:]
            return "OK", [b" ".join(str(u).encode() for u in uids)]
        uid = int(args[0])
        if uid not in self.caixa["mensagens"]:
            return "OK", [None]
        return "OK", [(f"1 (UID {uid} BODY[] {{9}}".encode(), self.caixa["mensagens"][uid]), b")"]

    def list(self):
        return "OK", [b'(\\HasNoChildren) "." "INBOX"', b'(\\HasNoChildren \\Sent) "." "INBOX.Sent"']

    def append(self, pasta, flags, data, bruto):
        self.caixa["enviados"].append((pasta, bruto))
        return "OK", []

    def logout(self):
        pass


class SmtpFalso:
    enviadas: list = []

    def send_message(self, msg):
        SmtpFalso.enviadas.append(msg)

    def quit(self):
        pass


@pytest.fixture
def caixa(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "email_usuario", "contato@associaçãoconectabci.com.br")
    monkeypatch.setattr(s, "email_senha", "senha-de-teste")
    dados = {"uidvalidity": 7, "mensagens": {}, "enviados": []}
    monkeypatch.setattr(em, "_imap", lambda: ImapFalso(dados))
    monkeypatch.setattr(em, "_smtp", lambda: SmtpFalso())
    monkeypatch.setattr(em, "talvez_sincronizar", lambda: None)  # sem thread nos testes
    SmtpFalso.enviadas = []
    return dados


def test_sem_configuracao_so_avisa(painel):  # noqa: F811
    _entrar(painel)
    pagina = painel.get("/plataforma/emails").text
    assert "Caixa de e-mail não configurada" in pagina and "EMAIL_USUARIO" in pagina
    assert 'href="/plataforma/emails"' in painel.get("/plataforma").text  # o menu já mostra


def test_le_a_caixa_liga_ao_lead_e_conta_nao_lidos(painel, caixa):  # noqa: F811
    from app.central import pre_cadastro

    pre_cadastro.registrar({"nome": "Marcos Pereira", "email": "marcos.pereira@exemplo.com", "whatsapp": "(24) 99812-3344",
                            "cidade": "Petrópolis/RJ", "perfil": "Corretor autônomo", "lgpd": "on"})  # fmt: skip
    caixa["mensagens"][3] = _mensagem(anexo=("proposta.pdf", b"%PDF-1.4 teste"))
    caixa["mensagens"][5] = _mensagem(de="spam@exemplo.com", assunto="Oferta", html="<p>Oi <img src='https://rastreio.exemplo/p.gif'><script>alert(1)</script></p>")
    csrf = _entrar(painel)
    r = painel.post("/plataforma/emails/atualizar", data={"csrf": csrf})
    assert r.headers["location"] == "/plataforma/emails?msg=atualizado&novas=2"
    # Ler de novo não duplica; mensagem nova entra.
    caixa["mensagens"][6] = _mensagem(assunto="Mais uma")
    assert em.sincronizar() == 1 and em.sincronizar() == 0

    lista = painel.get("/plataforma/emails").text
    assert "Quero saber do sistema" in lista and "Marcos Pereira" in lista and "Mais uma" in lista
    assert "contato@associaçãoconectabci.com.br" in lista
    assert re.search(r'E-mails <span class="contador">3</span>', painel.get("/plataforma").text)

    with central.sessao() as db:
        e = db.query(m.EmailAssociacao).filter_by(uid=3).one()
        spam = db.query(m.EmailAssociacao).filter_by(uid=5).one()
        assert (e.de_email, e.texto.strip(), e.anexos[0]["nome"]) == ("marcos.pereira@exemplo.com", "Olá!\nTudo bem?", "proposta.pdf")
        assert e.data.strftime("%d/%m/%Y %H:%M") == "28/10/2026 10:15"
    pagina = painel.get(f"/plataforma/emails/{e.id}").text
    assert "Lead do site · Marcos Pereira" in pagina and "proposta.pdf" in pagina
    assert 'E-mails <span class="contador">2</span>' in pagina  # abriu: lido
    r = painel.get(f"/plataforma/emails/{e.id}/anexos/0")
    assert r.content == b"%PDF-1.4 teste" and "attachment" in r.headers["content-disposition"]

    # HTML do e-mail: só num iframe isolado, sem scripts e sem imagens de fora (até pedir).
    pagina = painel.get(f"/plataforma/emails/{spam.id}").text
    assert 'sandbox="allow-popups allow-popups-to-escape-sandbox"' in pagina and "<script>alert" not in pagina
    assert "img-src data:" in pagina and "Mostrar imagens" in pagina
    assert "img-src https: data:" in painel.get(f"/plataforma/emails/{spam.id}?imagens=1").text

    painel.post(f"/plataforma/emails/{e.id}/nao-lido", data={"csrf": csrf})
    assert "Quero saber do sistema" in painel.get("/plataforma/emails?filtro=nao_lidos").text


def test_responder_e_escrever(painel, caixa):  # noqa: F811
    caixa["mensagens"][1] = _mensagem(mid="<original@exemplo.com>")
    em.sincronizar()
    csrf = _entrar(painel)
    with central.sessao() as db:
        e = db.query(m.EmailAssociacao).one()
    pagina = painel.get(f"/plataforma/emails/{e.id}").text
    assert 'value="marcos.pereira@exemplo.com"' in pagina and 'value="Re: Quero saber do sistema"' in pagina

    r = painel.post(f"/plataforma/emails/{e.id}/responder", data={
        "csrf": csrf, "para": "marcos.pereira@exemplo.com", "assunto": "Re: Quero saber do sistema", "mensagem": "Olá, Marcos! Vamos conversar."})  # fmt: skip
    assert r.headers["location"] == f"/plataforma/emails/{e.id}?msg=enviado"
    (enviada,) = SmtpFalso.enviadas
    assert enviada["In-Reply-To"] == "<original@exemplo.com>" and enviada["To"] == "marcos.pereira@exemplo.com"
    assert enviada["From"].addresses[0].addr_spec == "contato@xn--associaoconectabci-7sb3f.com.br"
    corpo = enviada.get_content()
    assert corpo.startswith("Olá, Marcos! Vamos conversar.") and "> Olá!" in corpo
    assert caixa["enviados"][0][0] == "INBOX.Sent"  # cópia no webmail
    assert "Respondido em" in painel.get(f"/plataforma/emails/{e.id}").text
    assert "Re: Quero saber do sistema" in painel.get("/plataforma/emails?filtro=enviados").text

    r = painel.post("/plataforma/emails/novo", data={"csrf": csrf, "para": "nao-e-email", "assunto": "Oi", "mensagem": "x"})
    assert r.status_code == 422 and "E-mail inválido" in r.text and 'value="nao-e-email"' in r.text
    r = painel.post("/plataforma/emails/novo", data={"csrf": csrf, "para": "a@exemplo.com, b@exemplo.com", "assunto": "Boas-vindas", "mensagem": "Olá!"})
    assert r.status_code == 303 and SmtpFalso.enviadas[-1]["To"] == "a@exemplo.com, b@exemplo.com"


def test_smtp_fora_do_ar_avisa(painel, caixa, monkeypatch):  # noqa: F811
    def falha():
        raise OSError("sem rede")

    monkeypatch.setattr(em, "_smtp", falha)
    csrf = _entrar(painel)
    r = painel.post("/plataforma/emails/novo", data={"csrf": csrf, "para": "a@exemplo.com", "assunto": "Oi", "mensagem": "x"})
    assert r.status_code == 422 and "servidor de e-mail não respondeu" in r.text
    with central.sessao() as db:
        assert db.query(m.EmailAssociacao).count() == 0


def test_mensagem_estranha_nao_trava_as_outras(painel, caixa):  # noqa: F811
    caixa["mensagens"][1] = b"isto nao e um e-mail \xff\xfe"
    caixa["mensagens"][2] = _mensagem(assunto="Normal")
    assert em.sincronizar() == 2
    with central.sessao() as db:
        assert {e.assunto for e in db.query(m.EmailAssociacao)} == {"(sem assunto)", "Normal"}


def test_emails_nao_pode_ser_slug(painel):  # noqa: F811
    from tests.central.test_painel import _nova

    assert _nova(painel, _entrar(painel), slug="emails").status_code == 422


def test_endereco_com_acento_vira_ascii():
    assert em.ascii_endereco("contato@associaçãoconectabci.com.br") == "contato@xn--associaoconectabci-7sb3f.com.br"
    assert em.exibir_endereco("contato@xn--associaoconectabci-7sb3f.com.br") == "contato@associaçãoconectabci.com.br"
    assert email.message_from_bytes(_mensagem(), policy=politica)["Subject"] == "Quero saber do sistema"
    assert agora()


def _arquivos_guardados():
    from pathlib import Path

    pasta = Path(get_settings().arquivos_dir) / "plataforma" / "emails"
    return sorted(p for p in pasta.rglob("*") if p.is_file()) if pasta.exists() else []


def test_enviar_com_anexos_e_baixar_depois(painel, caixa):  # noqa: F811
    csrf = _entrar(painel)
    assert 'enctype="multipart/form-data"' in painel.get("/plataforma/emails/novo").text
    r = painel.post("/plataforma/emails/novo", data={"csrf": csrf, "para": "ricardo@mendesimoveis.com.br", "assunto": "Contrato",
                                                     "mensagem": "Segue o contrato e a logo."},
                    files=[("anexos", ("contrato.pdf", b"%PDF-1.7 contrato", "application/pdf")),
                           ("anexos", ("logo.png", b"\x89PNG\r\n\x1a\nlogo", "image/png")),
                           ("anexos", ("", b"", "application/octet-stream"))])  # campo vazio do formulário  # fmt: skip
    assert r.status_code == 303, r.text
    enviada = SmtpFalso.enviadas[-1]
    anexos = {p.get_filename(): (p.get_content_type(), p.get_payload(decode=True)) for p in enviada.iter_attachments()}
    assert anexos == {"contrato.pdf": ("application/pdf", b"%PDF-1.7 contrato"), "logo.png": ("image/png", b"\x89PNG\r\n\x1a\nlogo")}
    assert len(_arquivos_guardados()) == 2
    # A cópia nos enviados do webmail leva os anexos também.
    copia = email.message_from_bytes(caixa["enviados"][-1][1], policy=politica)
    assert [p.get_filename() for p in copia.iter_attachments()] == ["contrato.pdf", "logo.png"]

    eid = r.headers["location"].split("/")[-1].split("?")[0]
    pagina = painel.get(f"/plataforma/emails/{eid}").text
    assert "contrato.pdf" in pagina and "logo.png" in pagina
    baixado = painel.get(f"/plataforma/emails/{eid}/anexos/0")
    assert baixado.content == b"%PDF-1.7 contrato" and "contrato.pdf" in baixado.headers["content-disposition"]


def test_responder_com_anexo(painel, caixa):  # noqa: F811
    caixa["mensagens"][1] = _mensagem(mid="<pergunta@exemplo.com>")
    em.sincronizar()
    csrf = _entrar(painel)
    with central.sessao() as db:
        e = db.query(m.EmailAssociacao).one()
    r = painel.post(f"/plataforma/emails/{e.id}/responder",
                    data={"csrf": csrf, "para": e.de_email, "assunto": "Re: Quero saber", "mensagem": "Segue a apresentação."},
                    files={"anexos": ("apresentacao.pdf", b"%PDF-1.4 apresentacao", "application/pdf")})  # fmt: skip
    assert r.headers["location"].endswith("?msg=enviado")
    assert [p.get_filename() for p in SmtpFalso.enviadas[-1].iter_attachments()] == ["apresentacao.pdf"]


def test_limites_dos_anexos(painel, caixa, monkeypatch):  # noqa: F811
    csrf = _entrar(painel)
    dados = {"csrf": csrf, "para": "a@exemplo.com", "assunto": "Oi", "mensagem": "x"}
    r = painel.post("/plataforma/emails/novo", data=dados, files={"anexos": ("instalar.exe", b"MZ...", "application/octet-stream")})
    assert r.status_code == 422 and "programas e scripts" in r.text and "Escolha os anexos de novo" in r.text
    monkeypatch.setattr(em, "LIMITE_ANEXOS", 10)
    r = painel.post("/plataforma/emails/novo", data=dados, files={"anexos": ("grande.pdf", b"%PDF" + b"x" * 20, "application/pdf")})
    assert r.status_code == 422 and "grandes demais" in r.text
    assert SmtpFalso.enviadas == [] and _arquivos_guardados() == []


def test_smtp_fora_do_ar_nao_deixa_anexo_guardado(painel, caixa, monkeypatch):  # noqa: F811
    def falha():
        raise OSError("sem rede")

    monkeypatch.setattr(em, "_smtp", falha)
    csrf = _entrar(painel)
    r = painel.post("/plataforma/emails/novo", data={"csrf": csrf, "para": "a@exemplo.com", "assunto": "Oi", "mensagem": "x"},
                    files={"anexos": ("contrato.pdf", b"%PDF-1.7", "application/pdf")})  # fmt: skip
    assert r.status_code == 422 and _arquivos_guardados() == []

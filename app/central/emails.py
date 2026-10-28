"""Caixa de e-mail da associação (contato@...) no painel da plataforma.

O servidor lê a caixa de entrada por IMAP (sem marcar nada como lido lá) e
guarda cada mensagem no banco central, para listar, contar as não lidas e
ligar o remetente a um lead, representante ou solicitação. Os anexos ficam
no servidor de e-mail e são baixados quando alguém abre. As respostas saem
por SMTP e ganham uma cópia na pasta de enviados da caixa."""

import email
import imaplib
import logging
import mimetypes
import re
import smtplib
import ssl
import threading
import time
import uuid
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from email.policy import default as politica
from email.utils import formataddr, formatdate, getaddresses, make_msgid, parseaddr, parsedate_to_datetime

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.central import models as m
from app.central import services as central
from app.core.armazenamento import ArmazenamentoIndisponivel, armazenamento, temporario
from app.core.config import get_settings
from app.core.errors import NaoEncontrado, RegraNegocio
from app.core.tempo import agora
from app.core.ulid import novo_ulid

log = logging.getLogger(__name__)

PRIMEIRA_CARGA = 200  # na primeira leitura, só as mais recentes
INTERVALO = 120  # segundos entre leituras automáticas
POR_PAGINA = 50
MAX_TEXTO = 2_000_000
_EMAIL = re.compile(r"^[^@\s,;<>]+@[^@\s,;<>]+\.[^@\s,;<>]+$")
FILTROS = {"entrada": "Caixa de entrada", "nao_lidos": "Não lidos", "enviados": "Enviados"}

# Anexos enviados pelo painel: guardados no S3 (plataforma/emails/<id do e-mail>/<ULID>)
# para baixar depois em "Enviados". Os recebidos ficam no servidor de e-mail.
MAX_ANEXOS = 10
LIMITE_ANEXOS = 20 * 1024 * 1024  # somados; a maioria dos provedores recusa acima de 25 MB
_PREFIXO_ANEXOS = "plataforma/emails"
_BLOQUEADOS = {"exe", "bat", "cmd", "com", "scr", "msi", "js", "vbs", "jar", "ps1", "sh"}

_trava = threading.Lock()
_ultima_leitura = 0.0


class EmailIndisponivel(RegraNegocio):
    def __init__(self, acao: str):
        super().__init__(f"Não foi possível {acao} agora: o servidor de e-mail não respondeu. Tente de novo em alguns minutos.")


def configurado() -> bool:
    s = get_settings()
    return bool(s.email_usuario and s.email_senha)


def ascii_endereco(endereco: str) -> str:
    """contato@associaçãoconectabci.com.br -> contato@xn--...: o IMAP e o SMTP só aceitam ASCII."""
    local, _, dominio = endereco.strip().rpartition("@")
    try:
        return f"{local}@{dominio.encode('idna').decode('ascii')}" if local else endereco.strip()
    except UnicodeError:
        return endereco.strip()


def exibir_endereco(endereco: str) -> str:
    local, _, dominio = endereco.rpartition("@")
    return f"{local}@{central.exibir_dominio(dominio)}" if local else endereco


def endereco() -> str:
    return ascii_endereco(get_settings().email_usuario)


# Conexões (os testes trocam estas duas) ---------------------------------
def _imap() -> imaplib.IMAP4:
    s = get_settings()
    c = imaplib.IMAP4_SSL(s.email_imap_host, s.email_imap_porta, ssl_context=ssl.create_default_context(), timeout=30)
    c.login(endereco(), s.email_senha)
    return c


def _smtp() -> smtplib.SMTP:
    s = get_settings()
    c = smtplib.SMTP_SSL(s.email_smtp_host, s.email_smtp_porta, context=ssl.create_default_context(), timeout=30)
    c.login(endereco(), s.email_senha)
    return c


def _sair(c) -> None:
    try:
        c.logout()
    except Exception:  # noqa: BLE001
        pass


# Leitura ---------------------------------------------------------------
def _texto_curto(valor: str | None, maximo: int) -> str:
    return (str(valor or "")).strip()[:maximo]


def _data(msg) -> datetime:
    try:
        d = parsedate_to_datetime(msg["Date"])
        if d.tzinfo:  # o banco guarda no horário local, sem fuso
            from zoneinfo import ZoneInfo

            d = d.astimezone(ZoneInfo(get_settings().fuso_horario)).replace(tzinfo=None)
        return d
    except Exception:  # noqa: BLE001 - data ausente ou malformada
        return agora()


def _corpo(msg, tipo: str) -> str:
    try:
        parte = msg.get_body(preferencelist=(tipo,))
        return parte.get_content()[:MAX_TEXTO] if parte is not None else ""
    except Exception:  # noqa: BLE001 - charset desconhecido etc.
        return ""


def _anexos(msg) -> list[dict]:
    lista = []
    for parte in msg.iter_attachments():
        try:
            conteudo = parte.get_payload(decode=True) or b""
        except Exception:  # noqa: BLE001
            conteudo = b""
        lista.append({"nome": parte.get_filename() or "anexo", "tipo": parte.get_content_type(), "tamanho": len(conteudo)})
    return lista


def _registro(bruto: bytes, uid: int, uidvalidity: int) -> m.EmailAssociacao:
    msg = email.message_from_bytes(bruto, policy=politica)
    nome, de = parseaddr(str(msg.get("From", "")))
    para = ", ".join(e for _, e in getaddresses([str(v) for v in msg.get_all("To", [])]) if e)
    cc = ", ".join(e for _, e in getaddresses([str(v) for v in msg.get_all("Cc", [])]) if e)
    return m.EmailAssociacao(
        id=str(uuid.uuid4()), pasta="entrada", uid=uid, uidvalidity=uidvalidity,
        message_id=_texto_curto(msg.get("Message-ID"), 300), em_resposta_a=_texto_curto(msg.get("In-Reply-To"), 300),
        de_nome=_texto_curto(nome, 200), de_email=_texto_curto(de, 200).lower(), para=para, cc=cc,
        assunto=_texto_curto(msg.get("Subject"), 500) or "(sem assunto)", data=_data(msg),
        texto=_corpo(msg, "plain"), html=_corpo(msg, "html"), anexos=_anexos(msg), lido=False, criado_em=agora(),
    )  # fmt: skip


def _bruto(c, uid: int) -> bytes:
    tipo, dados = c.uid("fetch", str(uid), "(BODY.PEEK[])")
    if tipo != "OK":
        raise NaoEncontrado("Mensagem não encontrada no servidor de e-mail.")
    for item in dados or []:
        if isinstance(item, tuple) and len(item) > 1:
            return item[1]
    raise NaoEncontrado("Mensagem não encontrada no servidor de e-mail.")


def sincronizar() -> int:
    """Traz as mensagens novas da caixa de entrada. Devolve quantas entraram."""
    global _ultima_leitura
    if not configurado() or not _trava.acquire(blocking=False):
        return 0
    novas = 0
    _ultima_leitura = time.monotonic()  # também quando falha: não tenta de novo a cada página
    try:
        try:
            c = _imap()
        except Exception as e:  # noqa: BLE001
            log.warning("E-mail: não conectou no IMAP: %s", e)
            raise EmailIndisponivel("ler os e-mails") from e
        try:
            c.select("INBOX", readonly=True)
            uidvalidity = int(c.response("UIDVALIDITY")[1][0])
            with central.sessao() as db:
                ultimo = db.scalar(sa.select(sa.func.max(m.EmailAssociacao.uid)).where(
                    m.EmailAssociacao.pasta == "entrada", m.EmailAssociacao.uidvalidity == uidvalidity)) or 0  # fmt: skip
            tipo, dados = c.uid("search", None, f"UID {ultimo + 1}:*")
            uids = sorted(int(u) for u in (dados[0] or b"").split() if int(u) > ultimo) if tipo == "OK" else []
            if not ultimo:
                uids = uids[-PRIMEIRA_CARGA:]
            for uid in uids:
                try:
                    registro = _registro(_bruto(c, uid), uid, uidvalidity)
                except Exception:  # noqa: BLE001 - uma mensagem estranha não trava as outras
                    log.exception("E-mail: não deu para ler a mensagem UID %s", uid)
                    continue
                with central.sessao() as db:
                    db.add(registro)
                    try:
                        db.commit()
                        novas += 1
                    except IntegrityError:  # o outro processo do servidor já gravou
                        db.rollback()
        finally:
            _sair(c)
        return novas
    finally:
        _trava.release()


def talvez_sincronizar() -> None:
    """Chamado ao abrir as páginas do painel: lê em segundo plano, no máximo a cada INTERVALO."""
    if configurado() and time.monotonic() - _ultima_leitura >= INTERVALO and not _trava.locked():

        def ler():
            try:
                sincronizar()
            except Exception as e:  # noqa: BLE001
                log.warning("E-mail: leitura automática falhou: %s", e)

        threading.Thread(target=ler, name="emails", daemon=True).start()


def anexo(e: m.EmailAssociacao, indice: int) -> tuple[str, str, bytes]:
    if not 0 <= indice < len(e.anexos or []):
        raise NaoEncontrado("Anexo não encontrado.")
    if e.pasta == "enviado":
        a = e.anexos[indice]
        if not a.get("chave"):
            raise NaoEncontrado("Anexo não encontrado.")
        try:
            with armazenamento().local(a["chave"]) as caminho:
                return a["nome"], a["tipo"], caminho.read_bytes()
        except FileNotFoundError:
            raise NaoEncontrado("Anexo não encontrado.") from None
        except Exception:
            log.exception("E-mail: não leu o anexo %s", a["chave"])
            raise ArmazenamentoIndisponivel() from None
    try:
        c = _imap()
    except Exception as erro:  # noqa: BLE001
        raise EmailIndisponivel("baixar o anexo") from erro
    try:
        c.select("INBOX", readonly=True)
        if int(c.response("UIDVALIDITY")[1][0]) != e.uidvalidity:
            raise NaoEncontrado("A mensagem mudou de lugar no servidor de e-mail.")
        msg = email.message_from_bytes(_bruto(c, e.uid), policy=politica)
    finally:
        _sair(c)
    partes = list(msg.iter_attachments())
    if indice >= len(partes):
        raise NaoEncontrado("Anexo não encontrado.")
    p = partes[indice]
    return p.get_filename() or "anexo", p.get_content_type(), p.get_payload(decode=True) or b""


# Painel ----------------------------------------------------------------
def listar(db: Session, filtro: str, pagina: int = 1) -> list[m.EmailAssociacao]:
    q = sa.select(m.EmailAssociacao)
    if filtro == "enviados":
        q = q.where(m.EmailAssociacao.pasta == "enviado")
    else:
        q = q.where(m.EmailAssociacao.pasta == "entrada")
        if filtro == "nao_lidos":
            q = q.where(m.EmailAssociacao.lido.is_(False))
    q = q.order_by(m.EmailAssociacao.data.desc()).offset((max(pagina, 1) - 1) * POR_PAGINA).limit(POR_PAGINA + 1)
    return list(db.scalars(q))


def nao_lidos(db: Session) -> int:
    return db.scalar(sa.select(sa.func.count()).where(
        m.EmailAssociacao.pasta == "entrada", m.EmailAssociacao.lido.is_(False))) or 0  # fmt: skip


def mensagem(db: Session, id_: str) -> m.EmailAssociacao:
    if (e := db.get(m.EmailAssociacao, id_)) is None:
        raise NaoEncontrado("E-mail não encontrado.")
    return e


def marcar(db: Session, e: m.EmailAssociacao, lido: bool) -> None:
    e.lido = lido
    db.commit()


def vinculos(db: Session, endereco_: str) -> list[tuple[str, str]]:
    """Quem é o remetente no sistema: lead do site, representante ou corretor de uma solicitação."""
    endereco_ = (endereco_ or "").strip().lower()
    if not endereco_:
        return []
    achados = []
    for x in db.scalars(sa.select(m.LeadAssociacao).where(sa.func.lower(m.LeadAssociacao.email) == endereco_)):
        achados.append((f"Lead do site · {x.nome}", "/plataforma/comercial/leads?situacao=todos"))
    for x in db.scalars(sa.select(m.Representante).where(sa.func.lower(m.Representante.email) == endereco_)):
        achados.append((f"Representante · {x.nome}", f"/plataforma/representantes/{x.id}"))
    for x in db.scalars(sa.select(m.SolicitacaoImplantacao).where(sa.func.lower(m.SolicitacaoImplantacao.email) == endereco_)):
        achados.append((f"Solicitação · {x.nome_imobiliaria}", f"/plataforma/financeiro/{x.id}"))
    return achados


def _destinatarios(texto: str) -> list[str]:
    lista = [ascii_endereco(x) for x in re.split(r"[,;\s]+", texto or "") if x.strip()]
    if not lista:
        raise RegraNegocio("Informe para quem enviar.")
    for x in lista:
        if not _EMAIL.match(x):
            raise RegraNegocio(f"E-mail inválido: {x}")
    return lista


def conferir_anexos(arquivos: list[tuple[str, str, bytes]]) -> list[tuple[str, str, bytes]]:
    """(nome, tipo, conteúdo) de cada arquivo escolhido; os vazios do formulário ficam de fora."""
    lista = [(Path(nome).name.strip()[:200], tipo, conteudo) for nome, tipo, conteudo in arquivos if nome and conteudo]
    if len(lista) > MAX_ANEXOS:
        raise RegraNegocio(f"No máximo {MAX_ANEXOS} anexos por e-mail.")
    if sum(len(c) for _, _, c in lista) > LIMITE_ANEXOS:
        raise RegraNegocio("Anexos grandes demais: no máximo 20 MB somados.")
    conferidos = []
    for nome, tipo, conteudo in lista:
        if nome.rsplit(".", 1)[-1].lower() in _BLOQUEADOS:
            raise RegraNegocio(f"{nome}: programas e scripts não podem ir como anexo.")
        if not re.match(r"^[\w.+-]+/[\w.+-]+$", tipo or "") or tipo == "application/octet-stream":
            tipo = mimetypes.guess_type(nome)[0] or "application/octet-stream"
        conferidos.append((nome, tipo, conteudo))
    return conferidos


def _guardar_anexos(email_id: str, anexos: list[tuple[str, str, bytes]]) -> list[dict]:
    loja, guardados = armazenamento(), []
    try:
        for nome, tipo, conteudo in anexos:
            chave = f"{_PREFIXO_ANEXOS}/{email_id}/{novo_ulid()}"
            provisorio = temporario()
            provisorio.write_bytes(conteudo)
            try:
                loja.gravar(chave, provisorio, tipo, {"origem": "plataforma", "email": email_id})
            finally:
                provisorio.unlink(missing_ok=True)
            guardados.append({"nome": nome, "tipo": tipo, "tamanho": len(conteudo), "chave": chave})
    except Exception:
        log.exception("E-mail: não guardou os anexos de %s", email_id)
        _apagar_anexos(guardados)
        raise ArmazenamentoIndisponivel() from None
    return guardados


def _apagar_anexos(guardados: list[dict]) -> None:
    for a in guardados:
        try:
            armazenamento().apagar(a["chave"])
        except Exception:  # noqa: BLE001
            log.warning("E-mail: sobrou o anexo %s no armazenamento", a["chave"])


def _citacao(original: m.EmailAssociacao) -> str:
    quando = original.data.strftime("%d/%m/%Y às %H:%M")
    quem = f"{original.de_nome} <{original.de_email}>" if original.de_nome else original.de_email
    linhas = (original.texto or "").strip().splitlines()
    return f"\n\nEm {quando}, {quem} escreveu:\n" + "\n".join(f"> {linha}" for linha in linhas)


def _guardar_nos_enviados(msg: EmailMessage) -> None:
    """Cópia na pasta de enviados da caixa (aparece no webmail). Se falhar, segue."""
    try:
        c = _imap()
    except Exception:  # noqa: BLE001
        return
    try:
        _, pastas = c.list()
        nomes = [re.search(rb'"([^"]+)"\s*$|(\S+)\s*$', p) for p in pastas or [] if p and b"\\Sent" in p]
        pasta = next((g.group(1) or g.group(2) for g in nomes if g), None)
        if pasta:
            c.append(pasta.decode(), "(\\Seen)", imaplib.Time2Internaldate(time.time()), msg.as_bytes())
    except Exception:  # noqa: BLE001
        log.warning("E-mail: não guardou a cópia nos enviados", exc_info=True)
    finally:
        _sair(c)


def enviar(db: Session, admin: m.Administrador, para: str, assunto: str, corpo: str,
           resposta_a: m.EmailAssociacao | None = None,
           anexos: list[tuple[str, str, bytes]] = ()) -> m.EmailAssociacao:  # fmt: skip
    if not configurado():
        raise RegraNegocio("A caixa de e-mail não está configurada no servidor.")
    destinatarios = _destinatarios(para)
    anexos = conferir_anexos(list(anexos))
    assunto, corpo = assunto.strip(), corpo.strip()
    if not assunto:
        raise RegraNegocio("Informe o assunto.")
    if not corpo:
        raise RegraNegocio("Escreva a mensagem.")
    s = get_settings()
    msg = EmailMessage()
    msg["From"] = formataddr((s.email_nome, endereco()))
    msg["To"] = ", ".join(destinatarios)
    msg["Subject"] = assunto
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=endereco().rpartition("@")[2])
    texto = corpo
    if resposta_a is not None:
        if resposta_a.message_id:
            msg["In-Reply-To"] = resposta_a.message_id
            msg["References"] = resposta_a.message_id
        texto += _citacao(resposta_a)
    msg.set_content(texto)
    for nome, tipo, conteudo in anexos:
        principal, _, sub = tipo.partition("/")
        msg.add_attachment(conteudo, maintype=principal, subtype=sub, filename=nome)
    email_id = str(uuid.uuid4())
    guardados = _guardar_anexos(email_id, anexos)  # antes de enviar: se o S3 falhar, nada sai
    try:
        c = _smtp()
        try:
            c.send_message(msg)
        finally:
            try:
                c.quit()
            except Exception:  # noqa: BLE001
                pass
    except (smtplib.SMTPException, OSError) as e:
        log.warning("E-mail: SMTP falhou: %s", e)
        _apagar_anexos(guardados)
        raise EmailIndisponivel("enviar o e-mail") from e
    _guardar_nos_enviados(msg)
    momento = agora()
    enviado = m.EmailAssociacao(
        id=email_id, pasta="enviado", message_id=str(msg["Message-ID"]),
        em_resposta_a=resposta_a.message_id if resposta_a else "", de_nome=s.email_nome, de_email=endereco(),
        para=", ".join(destinatarios), cc="", assunto=assunto[:500], data=momento, texto=texto, html="", anexos=guardados,
        lido=True, enviado_por_id=admin.id, criado_em=momento,
    )  # fmt: skip
    db.add(enviado)
    if resposta_a is not None:
        resposta_a.respondido_em = momento
    db.commit()
    return enviado


# Página HTML do e-mail num iframe isolado: sem scripts, sem acesso ao painel
# e, a não ser que peçam, sem imagens de fora (evita o "pixel" de leitura).
def html_isolado(html: str, imagens: bool) -> str:
    fontes = "https: data:" if imagens else "data:"
    cabeca = (f'<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src {fontes}; '
              "style-src 'unsafe-inline'; font-src data:\">"
              '<base target="_blank"><style>body{font:14px/1.5 system-ui,sans-serif;margin:12px;color:#151b2e}'
              "img{max-width:100%;height:auto}</style>")  # fmt: skip
    return cabeca + html

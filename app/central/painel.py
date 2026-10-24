"""Painel da plataforma (/plataforma): cadastro das imobiliárias — banco
próprio, domínios, paleta de cores, logotipo, situação e administrador de
cada uma. Só abre pelo endereço do servidor, nunca pelo domínio de uma
imobiliária."""

import socket
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.central import acesso
from app.central import infraestrutura as infra
from app.central import models as m
from app.central import services as central
from app.core.config import get_settings
from app.core.database import fabrica
from app.core.errors import RegraNegocio
from app.core.imobiliarias import Imobiliaria, buscar, identificada, normalizar_dominio, usar

PASTA = Path(__file__).parent
templates = Jinja2Templates(directory=PASTA / "templates")
templates.env.filters.update(tamanho=infra.tamanho, dinheiro=infra.dinheiro,
                             duracao=infra.duracao, mes=infra.mes)  # fmt: skip
templates.env.globals["porcento"] = infra.porcento
COR_PRIMARIA, COR_DESTAQUE = "#061a48", "#f5c432"  # a paleta padrão do site

MENSAGENS = {
    "criada": "Imobiliária criada: banco, tabelas e administrador prontos.",
    "salva": "Alterações salvas.",
    "logo": "Logotipo atualizado.",
    "logo-removido": "Logotipo removido.",
    "dominio": "Domínio adicionado. Falta apontar o DNS e ligar o HTTPS (veja abaixo).",
    "dominio-removido": "Domínio removido.",
    "ativada": "Imobiliária ativada.",
    "desativada": "Imobiliária desativada: API, site e portais deixam de abrir.",
    "admin": "Administrador salvo: ele já pode entrar no app de gestão.",
    "aws": "Dados da AWS atualizados (consultados no máximo a cada 10 minutos).",
}


def _so_pelo_servidor(request: Request) -> None:
    imob = identificada()
    host = normalizar_dominio(request.headers.get("host", ""))
    if imob and (host in imob.dominios or host.removeprefix("www.") in imob.dominios):
        raise HTTPException(404)


router = APIRouter(prefix="/plataforma", include_in_schema=False,
                   dependencies=[Depends(_so_pelo_servidor)])  # fmt: skip


def _db():
    with central.sessao() as db:
        yield db


Db = Annotated[Session, Depends(_db)]


def admin_logado(request: Request, db: Db) -> m.Administrador:
    a = acesso.do_token(db, request.cookies.get(acesso.COOKIE))
    if a is None:
        raise HTTPException(303, headers={"Location": "/plataforma/entrar"})
    return a


Admin = Annotated[m.Administrador, Depends(admin_logado)]


def _conferir(admin: m.Administrador, csrf: str) -> None:
    if not acesso.csrf_valido(admin, csrf):
        raise HTTPException(403, "Formulário expirado: recarregue a página.")


def _pagina(request: Request, nome: str, ctx: dict, status: int = 200) -> Response:
    resposta = templates.TemplateResponse(request, nome, ctx, status_code=status)
    resposta.headers.update({
        "Cache-Control": "no-store",
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
        "X-Robots-Tag": "noindex",
        "Referrer-Policy": "same-origin",
    })  # fmt: skip
    return resposta


def _ir(caminho: str, msg: str = "", erro: str = "") -> RedirectResponse:
    if msg:
        caminho += f"?msg={msg}"
    elif erro:
        caminho += f"?erro={quote(erro)}"
    return RedirectResponse(caminho, status_code=303)


def _base(request: Request, admin: m.Administrador | None, **extra) -> dict:
    return {
        "admin": admin,
        "csrf": acesso.token_csrf(admin) if admin else "",
        "msg": MENSAGENS.get(request.query_params.get("msg", ""), ""),
        "erro": request.query_params.get("erro", ""),
        "padrao": {"primaria": COR_PRIMARIA, "destaque": COR_DESTAQUE},
    } | extra


def _imobiliaria(slug: str) -> Imobiliaria:
    """A do cadastro em memória, relido agora (pode ter acabado de mudar)."""
    from app.core.imobiliarias import limpar_cadastro

    limpar_cadastro()
    imob = buscar(slug)
    if imob is None:
        raise HTTPException(404)
    return imob


# ------------------------------------------------------------- Entrar


@router.get("/entrar")
def entrar_pagina(request: Request, db: Db):
    if acesso.do_token(db, request.cookies.get(acesso.COOKIE)):
        return _ir("/plataforma")
    return _pagina(request, "entrar.html", _base(request, None))


@router.post("/entrar")
def entrar(request: Request, db: Db, login: Annotated[str, Form()] = "",
           senha: Annotated[str, Form()] = ""):  # fmt: skip
    try:
        a = acesso.autenticar(db, login, senha)
    except RegraNegocio as e:
        return _pagina(request, "entrar.html", _base(request, None, erro=e.mensagem, login=login), 422)
    resposta = _ir("/plataforma")
    resposta.set_cookie(
        acesso.COOKIE, acesso.criar_token(a), max_age=acesso.SESSAO_HORAS * 3600,
        httponly=True, samesite="strict", secure=request.url.scheme == "https", path="/plataforma",
    )  # fmt: skip
    return resposta


@router.post("/sair")
def sair(admin: Admin, csrf: Annotated[str, Form()] = ""):
    _conferir(admin, csrf)
    resposta = _ir("/plataforma/entrar")
    resposta.delete_cookie(acesso.COOKIE, path="/plataforma")
    return resposta


# ---------------------------------------------------------- Imobiliárias


@router.get("")
def lista(request: Request, db: Db, admin: Admin):
    imobiliarias = db.scalars(sa.select(m.Imobiliaria).order_by(m.Imobiliaria.nome)).all()
    return _pagina(request, "lista.html", _base(request, admin, imobiliarias=imobiliarias))


@router.get("/nova")
def nova_pagina(request: Request, admin: Admin):
    return _pagina(request, "nova.html", _base(request, admin, dados={}))


@router.post("/nova")
def nova(
    request: Request, admin: Admin,
    csrf: Annotated[str, Form()] = "",
    slug: Annotated[str, Form()] = "", nome: Annotated[str, Form()] = "",
    dominios: Annotated[str, Form()] = "", site_url: Annotated[str, Form()] = "",
    cor_primaria: Annotated[str, Form()] = "", cor_destaque: Annotated[str, Form()] = "",
    admin_nome: Annotated[str, Form()] = "", admin_login: Annotated[str, Form()] = "",
    admin_senha: Annotated[str, Form()] = "",
    logo: UploadFile | None = None,
):  # fmt: skip
    """Cria o banco, as tabelas, o cadastro e o administrador da imobiliária."""
    from app.modules.equipe.services import _validar_login, _validar_senha, aparar, criar_administrador

    _conferir(admin, csrf)
    dados = {"slug": slug, "nome": nome, "dominios": dominios, "site_url": site_url,
             "cor_primaria": cor_primaria, "cor_destaque": cor_destaque,
             "admin_nome": admin_nome, "admin_login": admin_login}  # fmt: skip
    try:
        conteudo = logo.file.read(central.LOGO_MAX + 1) if logo and logo.filename else None
        if conteudo:
            central.validar_logo(conteudo)
        if not admin_nome.strip():
            raise RegraNegocio("Informe o nome do administrador da imobiliária.")
        _validar_login(aparar(admin_login))
        _validar_senha(aparar(admin_senha))
        imob = central.criar_imobiliaria(
            slug, nome, site_url=site_url, dominios=dominios.replace(",", "\n").split(),
            cor_primaria=_cor(cor_primaria, COR_PRIMARIA),
            cor_destaque=_cor(cor_destaque, COR_DESTAQUE), logo=conteudo,
        )  # fmt: skip
        with usar(imob), fabrica(imob)() as db:
            criar_administrador(db, admin_nome, admin_login, admin_senha)
    except RegraNegocio as e:
        return _pagina(request, "nova.html", _base(request, admin, dados=dados, erro=e.mensagem), 422)
    return _ir(f"/plataforma/{imob.slug}", "criada")


# ------------------------------------------------------- Infraestrutura


@router.get("/infraestrutura")
def infraestrutura(request: Request, db: Db, admin: Admin):
    ctx = _base(request, admin, aws=infra.da_aws(), maquina=infra.maquina(),
                banco=infra.banco(db), bucket_nome=get_settings().aws_bucket)  # fmt: skip
    return _pagina(request, "infraestrutura.html", ctx)


@router.post("/infraestrutura")
def atualizar_infraestrutura(admin: Admin, csrf: Annotated[str, Form()] = ""):
    _conferir(admin, csrf)
    infra.da_aws(forcar=True)
    return _ir("/plataforma/infraestrutura", "aws")


def _cor(cor: str, padrao: str) -> str:
    """A cor padrão não é gravada: a imobiliária segue a paleta do sistema."""
    return "" if cor.strip().lower() == padrao else cor


def _ip_do_servidor(request: Request) -> str:
    try:
        return socket.gethostbyname(request.url.hostname or "")
    except OSError:
        return ""


def _aponta(dominio: str, ip: str) -> bool:
    try:
        return ip in {i[4][0] for i in socket.getaddrinfo(dominio, None, socket.AF_INET)}
    except OSError:
        return False


@router.get("/{slug}")
def detalhe(slug: str, request: Request, db: Db, admin: Admin):
    from app.modules.equipe.enums import PerfilAcesso
    from app.modules.equipe.models import Usuario

    r = db.get(m.Imobiliaria, slug)
    if r is None:
        raise HTTPException(404)
    imob = _imobiliaria(slug)
    ip = _ip_do_servidor(request)
    try:
        with fabrica(imob)() as tdb:
            admins = tdb.scalars(
                sa.select(Usuario).where(Usuario.perfil == PerfilAcesso.administrador)
                .order_by(Usuario.nome)
            ).all()  # fmt: skip
        tem_logo = central.logo(imob) is not None
        erro_banco = ""
    except Exception as e:  # noqa: BLE001 - mostra o problema no painel
        admins, tem_logo, erro_banco = [], False, str(e)[:300]
    ctx = _base(
        request, admin, r=r, imob=imob, ip=ip, admins=admins, tem_logo=tem_logo,
        erro_banco=erro_banco, dns={d.dominio: _aponta(d.dominio, ip) for d in r.dominios},
        endereco=f"{request.url.scheme}://{request.url.netloc}",
    )  # fmt: skip
    return _pagina(request, "imobiliaria.html", ctx)


@router.post("/{slug}")
def salvar(
    slug: str, db: Db, admin: Admin, csrf: Annotated[str, Form()] = "",
    nome: Annotated[str, Form()] = "", site_url: Annotated[str, Form()] = "",
    cor_primaria: Annotated[str, Form()] = "", cor_destaque: Annotated[str, Form()] = "",
):  # fmt: skip
    _conferir(admin, csrf)
    try:
        central.editar(db, slug, nome, site_url, _cor(cor_primaria, COR_PRIMARIA),
                       _cor(cor_destaque, COR_DESTAQUE))  # fmt: skip
    except RegraNegocio as e:
        return _ir(f"/plataforma/{slug}", erro=e.mensagem)
    return _ir(f"/plataforma/{slug}", "salva")


@router.get("/{slug}/logo")
def ver_logo(slug: str, admin: Admin):
    logo = central.logo(_imobiliaria(slug))
    if logo is None:
        raise HTTPException(404)
    return Response(logo[0], media_type=logo[1], headers={"Cache-Control": "no-store"})


@router.post("/{slug}/logo")
def enviar_logo(slug: str, admin: Admin, logo: UploadFile, csrf: Annotated[str, Form()] = ""):
    _conferir(admin, csrf)
    try:
        central.definir_logo(_imobiliaria(slug), logo.file.read(central.LOGO_MAX + 1))
    except RegraNegocio as e:
        return _ir(f"/plataforma/{slug}", erro=e.mensagem)
    return _ir(f"/plataforma/{slug}", "logo")


@router.post("/{slug}/logo/remover")
def remover_logo(slug: str, admin: Admin, csrf: Annotated[str, Form()] = ""):
    _conferir(admin, csrf)
    central.definir_logo(_imobiliaria(slug), None)
    return _ir(f"/plataforma/{slug}", "logo-removido")


@router.post("/{slug}/dominios")
def adicionar_dominio(slug: str, db: Db, admin: Admin, csrf: Annotated[str, Form()] = "",
                      dominio: Annotated[str, Form()] = ""):  # fmt: skip
    _conferir(admin, csrf)
    try:
        central.adicionar_dominio(db, slug, dominio)
    except RegraNegocio as e:
        return _ir(f"/plataforma/{slug}", erro=e.mensagem)
    return _ir(f"/plataforma/{slug}", "dominio")


@router.post("/{slug}/dominios/remover")
def remover_dominio(slug: str, db: Db, admin: Admin, csrf: Annotated[str, Form()] = "",
                    dominio: Annotated[str, Form()] = ""):  # fmt: skip
    _conferir(admin, csrf)
    central.remover_dominio(db, slug, dominio)
    return _ir(f"/plataforma/{slug}", "dominio-removido")


@router.post("/{slug}/situacao")
def situacao(slug: str, db: Db, admin: Admin, csrf: Annotated[str, Form()] = "",
             ativa: Annotated[str, Form()] = ""):  # fmt: skip
    _conferir(admin, csrf)
    central.definir_ativa(db, slug, ativa == "1")
    return _ir(f"/plataforma/{slug}", "ativada" if ativa == "1" else "desativada")


@router.post("/{slug}/administrador")
def administrador(
    slug: str, admin: Admin, csrf: Annotated[str, Form()] = "",
    nome: Annotated[str, Form()] = "", login: Annotated[str, Form()] = "",
    senha: Annotated[str, Form()] = "",
):  # fmt: skip
    """Cria o administrador da imobiliária ou redefine a senha dele."""
    from app.modules.equipe.services import criar_administrador

    _conferir(admin, csrf)
    imob = _imobiliaria(slug)
    try:
        with usar(imob), fabrica(imob)() as db:
            criar_administrador(db, nome or login, login, senha)
    except RegraNegocio as e:
        return _ir(f"/plataforma/{slug}", erro=e.mensagem)
    return _ir(f"/plataforma/{slug}", "admin")

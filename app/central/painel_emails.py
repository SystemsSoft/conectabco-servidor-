"""Painel > E-mails: a caixa contato@ da associação (ver app/central/emails.py).

Rotas registradas antes das do painel: senão /plataforma/{slug} pegaria
/plataforma/emails."""

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response

from app.central import emails as em
from app.central.painel import Admin, Db, _base, _conferir, _ir, _pagina, _so_pelo_servidor
from app.core.errors import RegraNegocio

router = APIRouter(prefix="/plataforma/emails", include_in_schema=False, dependencies=[Depends(_so_pelo_servidor)])

MENSAGENS = {
    "enviado": "E-mail enviado.",
    "atualizado": "Caixa de entrada atualizada.",
    "nao-lido": "Marcado como não lido.",
}


def _ctx(request: Request, admin, **extra) -> dict:
    ctx = _base(request, admin, configurado=em.configurado(),
                endereco=em.exibir_endereco(em.endereco()) if em.configurado() else "", **extra)  # fmt: skip
    if msg := MENSAGENS.get(request.query_params.get("msg", "")):
        ctx["msg"] = msg
    return ctx


@router.get("")
def caixa(request: Request, db: Db, admin: Admin, filtro: str = "entrada", pagina: int = 1):
    filtro = filtro if filtro in em.FILTROS else "entrada"
    lista = em.listar(db, filtro, pagina)
    ctx = _ctx(request, admin, emails=lista[: em.POR_PAGINA], mais=len(lista) > em.POR_PAGINA, filtro=filtro,
               filtros=em.FILTROS, pagina=max(pagina, 1), nao_lidos=em.nao_lidos(db))  # fmt: skip
    return _pagina(request, "emails.html", ctx)


@router.post("/atualizar")
def atualizar(admin: Admin, csrf: Annotated[str, Form()] = ""):
    _conferir(admin, csrf)
    try:
        novas = em.sincronizar()
    except RegraNegocio as e:
        return _ir("/plataforma/emails", erro=e.mensagem)
    return RedirectResponse(f"/plataforma/emails?msg=atualizado&novas={novas}", status_code=303)


@router.get("/novo")
def novo_pagina(request: Request, admin: Admin, para: str = "", assunto: str = ""):
    return _pagina(request, "email_novo.html", _ctx(request, admin, dados={"para": para, "assunto": assunto, "mensagem": ""}))


@router.post("/novo")
def novo(request: Request, db: Db, admin: Admin, csrf: Annotated[str, Form()] = "",
         para: Annotated[str, Form()] = "", assunto: Annotated[str, Form()] = "",
         mensagem: Annotated[str, Form()] = ""):  # fmt: skip
    _conferir(admin, csrf)
    try:
        enviado = em.enviar(db, admin, para, assunto, mensagem)
    except RegraNegocio as e:
        ctx = _ctx(request, admin, dados={"para": para, "assunto": assunto, "mensagem": mensagem}, erro=e.mensagem)
        return _pagina(request, "email_novo.html", ctx, 422)
    return _ir(f"/plataforma/emails/{enviado.id}", "enviado")


@router.get("/{id_}")
def ver(id_: str, request: Request, db: Db, admin: Admin, imagens: bool = False):
    e = em.mensagem(db, id_)
    if not e.lido:
        em.marcar(db, e, True)
    outro = e.para.split(",")[0].strip() if e.pasta == "enviado" else e.de_email
    assunto = e.assunto if e.assunto.lower().startswith(("re:", "res:")) else f"Re: {e.assunto}"
    ctx = _ctx(request, admin, e=e, vinculos=em.vinculos(db, outro), imagens=imagens,
               html=em.html_isolado(e.html, imagens) if e.html else "",
               resposta={"para": e.de_email if e.pasta == "entrada" else e.para, "assunto": assunto, "mensagem": ""})  # fmt: skip
    return _pagina(request, "email.html", ctx)


@router.post("/{id_}/responder")
def responder(id_: str, request: Request, db: Db, admin: Admin, csrf: Annotated[str, Form()] = "",
              para: Annotated[str, Form()] = "", assunto: Annotated[str, Form()] = "",
              mensagem: Annotated[str, Form()] = ""):  # fmt: skip
    _conferir(admin, csrf)
    e = em.mensagem(db, id_)
    try:
        em.enviar(db, admin, para, assunto, mensagem, resposta_a=e)
    except RegraNegocio as erro:
        return _ir(f"/plataforma/emails/{id_}", erro=erro.mensagem)
    return _ir(f"/plataforma/emails/{id_}", "enviado")


@router.post("/{id_}/nao-lido")
def nao_lido(id_: str, db: Db, admin: Admin, csrf: Annotated[str, Form()] = ""):
    _conferir(admin, csrf)
    em.marcar(db, em.mensagem(db, id_), False)
    return _ir("/plataforma/emails", "nao-lido")


@router.get("/{id_}/anexos/{indice}")
def baixar_anexo(id_: str, indice: int, db: Db, admin: Admin):
    try:
        nome, tipo, conteudo = em.anexo(em.mensagem(db, id_), indice)
    except RegraNegocio as e:
        return _ir(f"/plataforma/emails/{id_}", erro=e.mensagem)
    # Sempre como download: um HTML ou SVG anexado não roda dentro do painel.
    return Response(conteudo, media_type=tipo if tipo != "text/html" else "application/octet-stream", headers={
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(nome)}",
        "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})

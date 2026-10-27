"""Páginas públicas de contratação (/contratar), abertas pelo site
institucional. Só pelo endereço do servidor; o link de cada contrato é o
`token` (sem login)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response

from app.central import contratacao as cc
from app.central import representantes as rep
from app.central.painel import Db, _pagina, _so_pelo_servidor
from app.central.pre_cadastro import _dentro_do_limite
from app.core.armazenamento import armazenamento
from app.core.errors import NaoEncontrado, RegraNegocio

router = APIRouter(prefix="/contratar", include_in_schema=False, dependencies=[Depends(_so_pelo_servidor)])


def _ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _ctx(**extra) -> dict:
    return {"ufs": rep.UFS, "metodos": cc.METODOS, "assinador": cc.ASSINADOR_GOVBR} | extra


def _contrato_ou_404(request: Request, db, token: str):
    try:
        return cc.por_token(db, token), None
    except NaoEncontrado as e:
        return None, _pagina(request, "contratar/invalido.html", _ctx(), 404)


@router.get("")
def formulario(request: Request):
    return _pagina(request, "contratar/dados.html", _ctx(dados={}))


@router.post("")
async def iniciar(request: Request, db: Db):
    dados = {k: str(v) for k, v in (await request.form()).items()}
    if not _dentro_do_limite(f"contratar:{_ip(request)}"):
        return _pagina(request, "contratar/dados.html",
                       _ctx(dados=dados, erro="Muitas tentativas seguidas. Tente de novo mais tarde."), 429)  # fmt: skip
    try:
        c = cc.iniciar(db, dados)
    except RegraNegocio as e:
        return _pagina(request, "contratar/dados.html", _ctx(dados=dados, erro=e.mensagem), 422)
    return RedirectResponse(f"/contratar/{c.token}", status_code=303)


@router.get("/{token}")
def contrato(token: str, request: Request, db: Db):
    c, erro = _contrato_ou_404(request, db, token)
    if erro:
        return erro
    nome = "contratar/assinado.html" if c.situacao == "assinado" else "contratar/contrato.html"
    return _pagina(request, nome, _ctx(c=c, erro=request.query_params.get("erro", "")))


@router.get("/{token}/contrato.pdf")
def contrato_pdf(token: str, request: Request, db: Db, baixar: bool = False):
    c, erro = _contrato_ou_404(request, db, token)
    if erro:
        return erro
    disposicao = "attachment" if baixar else "inline"
    if c.situacao == "assinado":  # a via assinada, como foi guardada
        loja = armazenamento()
        if url := loja.link(c.chave_assinado, "application/pdf", "contrato-assinado.pdf", not baixar, "no-store"):
            return RedirectResponse(url, status_code=307, headers={"Cache-Control": "no-store"})
        return FileResponse(loja.caminho(c.chave_assinado), media_type="application/pdf",
                            filename="contrato-assinado.pdf", content_disposition_type=disposicao)  # fmt: skip
    return Response(cc.pdf(c), media_type="application/pdf", headers={
        "Content-Disposition": f'{disposicao}; filename="contrato-conecta-do-brasil.pdf"', "Cache-Control": "no-store"})


@router.post("/{token}/assinar")
def assinar(token: str, request: Request, db: Db, nome: Annotated[str, Form()] = "",
            aceite: Annotated[str, Form()] = ""):  # fmt: skip
    c, erro = _contrato_ou_404(request, db, token)
    if erro:
        return erro
    try:
        cc.assinar_eletronicamente(db, c, nome, aceite, _ip(request), request.headers.get("user-agent", ""))
    except RegraNegocio as e:
        return _pagina(request, "contratar/contrato.html", _ctx(c=c, erro=e.mensagem, nome=nome), 422)
    return RedirectResponse(f"/contratar/{token}", status_code=303)


@router.post("/{token}/govbr")
def enviar_govbr(token: str, request: Request, db: Db, arquivo: UploadFile):
    c, erro = _contrato_ou_404(request, db, token)
    if erro:
        return erro
    try:
        cc.receber_govbr(db, c, arquivo.file, _ip(request), request.headers.get("user-agent", ""))
    except RegraNegocio as e:
        return _pagina(request, "contratar/contrato.html", _ctx(c=c, erro=e.mensagem, aba="govbr"), 422)
    return RedirectResponse(f"/contratar/{token}", status_code=303)

"""Área do representante (/representante): com login e senha cadastrados no
painel da plataforma, o representante envia os corretores para implantação e
acompanha a situação de cada um. Só abre pelo endereço do servidor."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.datastructures import UploadFile as ArquivoEnviado
from sqlalchemy.orm import Session

from app.central import acesso
from app.central import models as m
from app.central import contratacao as cc
from app.central import representantes as rep
from app.central.painel import _db, _pagina, _so_pelo_servidor
from app.core.errors import RegraNegocio
from app.core.tempo import agora

router = APIRouter(prefix="/representante", include_in_schema=False,
                   dependencies=[Depends(_so_pelo_servidor)])  # fmt: skip
Db = Annotated[Session, Depends(_db)]

MENSAGENS = {
    "enviada": "Corretor enviado para implantação, com o contrato assinado. A associação vai entrar em contato.",
    "link": "Corretor enviado. Agora envie o link abaixo para ele assinar o contrato.",
}


def representante_logado(request: Request, db: Db) -> m.Representante:
    r = acesso.do_token(db, request.cookies.get(acesso.COOKIE_REPRESENTANTE), m.Representante)
    if r is None:
        raise HTTPException(303, headers={"Location": "/representante/entrar"})
    return r


Logado = Annotated[m.Representante, Depends(representante_logado)]


def _ctx(request: Request, r: m.Representante | None, **extra) -> dict:
    return {
        "representante": r,
        "csrf": acesso.token_csrf(r) if r else "",
        "msg": MENSAGENS.get(request.query_params.get("msg", ""), ""),
        "erro": request.query_params.get("erro", ""),
        "situacoes": rep.SITUACOES,
        "ufs": rep.UFS,
        "metodos": cc.METODOS,
    } | extra


def _conferir(r: m.Representante, csrf: str) -> None:
    if not acesso.csrf_valido(r, csrf):
        raise HTTPException(403, "Formulário expirado: recarregue a página.")


@router.get("/entrar")
def entrar_pagina(request: Request, db: Db):
    if acesso.do_token(db, request.cookies.get(acesso.COOKIE_REPRESENTANTE), m.Representante):
        return RedirectResponse("/representante", status_code=303)
    return _pagina(request, "representante/entrar.html", _ctx(request, None))


@router.post("/entrar")
def entrar(request: Request, db: Db, login: Annotated[str, Form()] = "",
           senha: Annotated[str, Form()] = ""):  # fmt: skip
    try:
        r = acesso.autenticar(db, login, senha, m.Representante)
    except RegraNegocio as e:
        return _pagina(request, "representante/entrar.html", _ctx(request, None, erro=e.mensagem, login=login), 422)
    resposta = RedirectResponse("/representante", status_code=303)
    resposta.set_cookie(
        acesso.COOKIE_REPRESENTANTE, acesso.criar_token(r), max_age=acesso.SESSAO_HORAS * 3600,
        httponly=True, samesite="strict", secure=request.url.scheme == "https", path="/representante",
    )  # fmt: skip
    return resposta


@router.post("/sair")
def sair(r: Logado, csrf: Annotated[str, Form()] = ""):
    _conferir(r, csrf)
    resposta = RedirectResponse("/representante/entrar", status_code=303)
    resposta.delete_cookie(acesso.COOKIE_REPRESENTANTE, path="/representante")
    return resposta


@router.get("")
def inicio(request: Request, db: Db, r: Logado):
    lista = rep.solicitacoes(db, representante_id=r.id)
    contratos = {s.id: cc.da_solicitacao(db, s.id) for s in lista}
    return _pagina(request, "representante/inicio.html", _ctx(request, r, solicitacoes=lista, contratos=contratos))


@router.get("/novo")
def novo_pagina(request: Request, r: Logado):
    return _pagina(request, "representante/novo.html", _ctx(request, r, dados={"contrato": "link"}))


@router.post("/novo")
async def novo(request: Request, db: Db, r: Logado):
    """Corretor com os dados do contrato; o contrato vai anexado (já assinado)
    ou por link de assinatura para o corretor."""
    formulario = await request.form()
    _conferir(r, str(formulario.get("csrf", "")))
    arquivos = {k: v for k, v in formulario.items() if isinstance(v, ArquivoEnviado)}
    dados = {k: str(v) for k, v in formulario.items() if k not in arquivos}
    try:
        s, _ = cc.enviar_pelo_representante(db, r, dados, arquivos.get("logo"), arquivos.get("contrato_assinado"))
    except RegraNegocio as e:
        return _pagina(request, "representante/novo.html", _ctx(request, r, dados=dados, erro=e.mensagem), 422)
    if dados.get("contrato") == "link":
        return RedirectResponse(f"/representante/corretores/{s.id}?msg=link", status_code=303)
    return RedirectResponse("/representante?msg=enviada", status_code=303)


@router.get("/corretores/{id_}")
def corretor(id_: str, request: Request, db: Db, r: Logado):
    """Um corretor enviado por este representante: situação e o link de assinatura."""
    s = db.get(m.SolicitacaoImplantacao, id_)
    if s is None or s.representante_id != r.id:
        raise HTTPException(404)
    contrato = cc.da_solicitacao(db, s.id)
    link = f"{str(request.base_url).rstrip('/')}/contratar/{contrato.token}" if contrato else ""
    expirado = bool(contrato and contrato.situacao == "aguardando" and agora() - contrato.criado_em > cc.VALIDADE)
    return _pagina(request, "representante/corretor.html",
                   _ctx(request, r, s=s, contrato=contrato, link=link, expirado=expirado))  # fmt: skip

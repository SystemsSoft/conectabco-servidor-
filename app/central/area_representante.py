"""Área do representante (/representante): com login e senha cadastrados no
painel da plataforma, o representante envia os corretores para implantação e
acompanha a situação de cada um. Só abre pelo endereço do servidor."""

from dataclasses import fields
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.central import acesso
from app.central import models as m
from app.central import representantes as rep
from app.central.painel import _db, _pagina, _so_pelo_servidor
from app.core.errors import RegraNegocio

router = APIRouter(prefix="/representante", include_in_schema=False,
                   dependencies=[Depends(_so_pelo_servidor)])  # fmt: skip
Db = Annotated[Session, Depends(_db)]

MENSAGENS = {"enviada": "Corretor enviado para implantação. A associação vai entrar em contato."}


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
    return _pagina(request, "representante/inicio.html",
                   _ctx(request, r, solicitacoes=rep.solicitacoes(db, representante_id=r.id)))  # fmt: skip


@router.get("/novo")
def novo_pagina(request: Request, r: Logado):
    return _pagina(request, "representante/novo.html", _ctx(request, r, dados=rep.DadosCorretor()))


@router.post("/novo")
async def novo(request: Request, db: Db, r: Logado):
    formulario = await request.form()
    _conferir(r, str(formulario.get("csrf", "")))
    dados = rep.DadosCorretor(**{f.name: str(formulario.get(f.name, "")) for f in fields(rep.DadosCorretor)})
    try:
        rep.enviar_solicitacao(db, r, dados)
    except RegraNegocio as e:
        return _pagina(request, "representante/novo.html", _ctx(request, r, dados=dados, erro=e.mensagem), 422)
    return RedirectResponse("/representante?msg=enviada", status_code=303)

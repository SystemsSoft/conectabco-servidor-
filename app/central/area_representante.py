"""Área do representante (/representante): com login e senha cadastrados no
painel da plataforma, o representante envia os corretores para implantação e
acompanha a situação de cada um. Em "Minha conta" ele pode conectar a conta
Google e, daí em diante, entrar com ela. Só abre pelo endereço do servidor."""

from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.datastructures import UploadFile as ArquivoEnviado
from sqlalchemy.orm import Session

import sqlalchemy as sa

from app.central import acesso
from app.central import google
from app.central import models as m
from app.central import contratacao as cc
from app.central import representantes as rep
from app.central import tutoriais as tut
from app.central import services as central
from app.central.painel import _db, _pagina, _so_pelo_servidor
from app.core.errors import RegraNegocio
from app.core.tempo import agora

router = APIRouter(prefix="/representante", include_in_schema=False,
                   dependencies=[Depends(_so_pelo_servidor)])  # fmt: skip
Db = Annotated[Session, Depends(_db)]

MENSAGENS = {
    "enviada": "Corretor enviado para implantação, com o contrato assinado. A associação vai entrar em contato.",
    "link": "Corretor enviado. Agora envie o link abaixo para ele assinar o contrato.",
    "google-conectado": "Conta Google conectada. Nos próximos acessos, use \"Entrar com Google\".",
    "google-desconectado": "Conta Google desconectada. Entre com usuário e senha.",
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
        "caminho": request.url.path,
        "csrf": acesso.token_csrf(r) if r else "",
        "msg": MENSAGENS.get(request.query_params.get("msg", ""), ""),
        "erro": request.query_params.get("erro", ""),
        "situacoes": rep.SITUACOES,
        "ufs": rep.UFS,
        "metodos": cc.METODOS,
        "subdominio_base": central.exibir_dominio(base) if (base := central.subdominio_base()) else "",
        "firebase": google.configuracao(),
        "firebase_sdk": google.SDK,
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
    return _abrir_sessao(request, r)


def _abrir_sessao(request: Request, r: m.Representante) -> RedirectResponse:
    resposta = RedirectResponse("/representante", status_code=303)
    resposta.set_cookie(
        acesso.COOKIE_REPRESENTANTE, acesso.criar_token(r), max_age=acesso.SESSAO_HORAS * 3600,
        httponly=True, samesite="strict", secure=request.url.scheme == "https", path="/representante",
    )  # fmt: skip
    return resposta


@router.post("/entrar/google")
def entrar_google(request: Request, db: Db, id_token: Annotated[str, Form()] = ""):
    """Só para quem já conectou a conta Google em "Minha conta" (depois de
    entrar com usuário e senha): uma conta desconhecida não cria acesso."""
    try:
        uid, _ = google.conta_do_token(id_token)
        r = db.scalar(sa.select(m.Representante).where(m.Representante.google_uid == uid))
        if r is None:
            raise RegraNegocio("Esta conta Google não está conectada a nenhum representante. "
                               "Entre com usuário e senha e conecte-a em \"Minha conta\".")  # fmt: skip
        if not r.ativo:
            raise RegraNegocio("Seu acesso está desativado.")
    except RegraNegocio as e:
        return _pagina(request, "representante/entrar.html", _ctx(request, None, erro=e.mensagem), 422)
    r.ultimo_acesso = agora()
    db.commit()
    return _abrir_sessao(request, r)


@router.post("/sair")
def sair(r: Logado, csrf: Annotated[str, Form()] = ""):
    _conferir(r, csrf)
    resposta = RedirectResponse("/representante/entrar", status_code=303)
    resposta.delete_cookie(acesso.COOKIE_REPRESENTANTE, path="/representante")
    return resposta


@router.get("/conta")
def conta(request: Request, r: Logado):
    return _pagina(request, "representante/conta.html", _ctx(request, r))


@router.post("/conta/google")
def conectar_google(request: Request, db: Db, r: Logado, csrf: Annotated[str, Form()] = "",
                    id_token: Annotated[str, Form()] = ""):  # fmt: skip
    _conferir(r, csrf)
    try:
        uid, email = google.conta_do_token(id_token)
        outro = db.scalar(sa.select(m.Representante).where(m.Representante.google_uid == uid))
        if outro is not None and outro.id != r.id:
            raise RegraNegocio("Esta conta Google já está conectada a outro representante.")
    except RegraNegocio as e:
        return _pagina(request, "representante/conta.html", _ctx(request, r, erro=e.mensagem), 422)
    r.google_uid, r.google_email = uid, email
    db.commit()
    return RedirectResponse("/representante/conta?msg=google-conectado", status_code=303)


@router.post("/conta/google/desconectar")
def desconectar_google(db: Db, r: Logado, csrf: Annotated[str, Form()] = ""):
    _conferir(r, csrf)
    r.google_uid, r.google_email = None, ""
    db.commit()
    return RedirectResponse("/representante/conta?msg=google-desconectado", status_code=303)


@router.get("")
def inicio(request: Request, db: Db, r: Logado):
    lista = rep.solicitacoes(db, representante_id=r.id)
    contratos = {s.id: cc.da_solicitacao(db, s.id) for s in lista}
    return _pagina(request, "representante/inicio.html", _ctx(request, r, solicitacoes=lista, contratos=contratos))


@router.get("/tutorial")
def tutorial_pagina(request: Request, r: Logado):
    ctx = _ctx(request, r, capitulos=tut.CAPITULOS_REPRESENTANTE, disponivel=tut.disponivel(tut.REPRESENTANTE))
    return _pagina(request, "representante/tutorial.html", ctx)


@router.get("/tutorial.mp4")
def tutorial_video(r: Logado):
    return tut.entregar(tut.REPRESENTANTE)


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

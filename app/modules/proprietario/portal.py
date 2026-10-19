"""Área do proprietário no site (/proprietario): imóveis e contratos,
repasses, auditorias publicadas (com vídeos e transcrição) e manutenções.
Sessão em cookie HttpOnly próprio (não vale na Área do inquilino)."""

import hmac
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.core.acesso_portal import SESSAO_HORAS
from app.core.database import get_db
from app.core.errors import NaoEncontrado, RegraNegocio
from app.core.tempo import agora
from app.modules.arquivos.api import resposta_arquivo
from app.modules.arquivos.models import Arquivo
from app.modules.arquivos.services import caminho as caminho_arquivo
from app.modules.auditoria import relatorio
from app.modules.crm.models import Contato, Imovel
from app.modules.inquilino.services import site_seguro
from app.modules.manutencao.enums import StatusManutencao
from app.modules.proprietario import services as s
from app.modules.proprietario.models import AcessoProprietario
from app.modules.site.publico import _base, templates

router = APIRouter(prefix="/proprietario", include_in_schema=False)
Db = Annotated[Session, Depends(get_db)]
COOKIE = "portal_proprietario"


class _Redirecionar(Exception):
    def __init__(self, destino: str):
        self.destino = destino


def _ir(destino: str) -> RedirectResponse:
    return RedirectResponse(destino, status_code=303)


def _com_erro(destino: str, erro: str) -> RedirectResponse:
    return _ir(f"{destino}?{urlencode({'erro': erro})}")


def _cabecalhos(r: Response) -> Response:
    r.headers["Cache-Control"] = "no-store"  # dados pessoais: sem cache
    r.headers["X-Frame-Options"] = "DENY"
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["Referrer-Policy"] = "same-origin"
    return r


def _resposta(nome: str, ctx: dict, status: int = 200) -> Response:
    if not ctx["cfg"].no_ar or not ctx["cfg"].mostrar_area_proprietario:
        return templates.TemplateResponse(ctx["request"], "manutencao.html", ctx, status_code=503)
    return _cabecalhos(templates.TemplateResponse(ctx["request"], nome, ctx, status_code=status))


def _acesso(request: Request, db: Session) -> AcessoProprietario:
    acesso = s.acesso_do_token(db, request.cookies.get(COOKIE))
    if acesso is None:
        raise _Redirecionar("/proprietario/entrar")
    return acesso


def _contexto(request: Request, db: Session, aba: str, exigir_senha_nova: bool = True) -> dict:
    acesso = _acesso(request, db)
    if exigir_senha_nova and acesso.trocar_senha:
        raise _Redirecionar("/proprietario/senha")
    contratos = s.contratos_do(db, acesso.contato_id)
    return _base(
        request, db, acesso=acesso, contato=db.get(Contato, acesso.contato_id),
        contratos=contratos, imoveis={c.imovel_id: db.get(Imovel, c.imovel_id) for c in contratos},
        csrf=s.token_csrf(acesso), aba=aba, pagina_atual="proprietario", hoje=agora().date(),
    )  # fmt: skip


def _pagina(nome: str, aba: str, exigir_senha_nova: bool = True):
    def decorador(funcao):
        def rota(request: Request, db: Db):
            try:
                ctx = _contexto(request, db, aba, exigir_senha_nova)
            except _Redirecionar as r:
                return _ir(r.destino)
            extra = funcao(request, db, ctx)
            if isinstance(extra, Response):
                return extra
            return _resposta(nome, ctx | (extra or {}))

        rota.__name__ = funcao.__name__
        return rota

    return decorador


def _cookie(r: Response, request: Request, acesso: AcessoProprietario) -> Response:
    r.set_cookie(
        COOKIE, s.criar_token(acesso), max_age=SESSAO_HORAS * 3600, path="/proprietario",
        httponly=True, samesite="lax", secure=request.url.scheme == "https" or site_seguro(),
    )  # fmt: skip
    return r


# ------------------------------------------------------------------ Login


@router.get("/entrar")
def entrar(request: Request, db: Db):
    if s.acesso_do_token(db, request.cookies.get(COOKIE)):
        return _ir("/proprietario")
    return _resposta("proprietario/entrar.html", _base(request, db, pagina_atual="proprietario"))


@router.post("/entrar")
def entrar_enviar(request: Request, db: Db, documento: Annotated[str, Form()] = "",
                  senha: Annotated[str, Form()] = ""):  # fmt: skip
    try:
        acesso = s.autenticar(db, documento, senha)
    except RegraNegocio as e:
        return _com_erro("/proprietario/entrar", e.mensagem)
    return _cookie(_ir("/proprietario/senha" if acesso.trocar_senha else "/proprietario"), request, acesso)


@router.post("/sair")
def sair():
    r = _ir("/proprietario/entrar")
    r.delete_cookie(COOKIE, path="/proprietario")
    return r


@router.get("/senha")
@_pagina("proprietario/senha.html", "senha", exigir_senha_nova=False)
def senha(request, db, ctx):
    return None


@router.post("/senha")
def senha_enviar(request: Request, db: Db, atual: Annotated[str, Form()] = "",
                 nova: Annotated[str, Form()] = "", repetida: Annotated[str, Form()] = "",
                 csrf: Annotated[str, Form()] = ""):  # fmt: skip
    try:
        acesso = _acesso(request, db)
    except _Redirecionar as r:
        return _ir(r.destino)
    try:
        if not hmac.compare_digest(s.token_csrf(acesso), csrf or ""):
            raise RegraNegocio("Sessão expirada. Recarregue a página e tente de novo.")
        s.trocar_senha(db, acesso, atual, nova, repetida)
    except RegraNegocio as e:
        return _com_erro("/proprietario/senha", e.mensagem)
    return _cookie(_ir("/proprietario?ok=Senha alterada."), request, acesso)


# ---------------------------------------------------------------- Páginas


@router.get("")
@_pagina("proprietario/painel.html", "inicio")
def painel(request, db, ctx):
    contato_id = ctx["acesso"].contato_id
    linhas = s.repasses(db, contato_id)
    hoje = ctx["hoje"]
    return {
        "ativos": [c for c in ctx["contratos"] if c.status.value == "ativo"],
        "cotas": {c.id: s.cota(c, contato_id) for c in ctx["contratos"]},
        "ultimos_repasses": linhas[:4],
        "recebido_ano": round(sum(x.liquido for x in linhas
                                  if x.repassado_em and x.repassado_em.year == hoje.year), 2),  # fmt: skip
        "a_repassar": round(sum(x.liquido for x in linhas if not x.repassado_em), 2),
        "auditorias": s.auditorias_publicadas(db, contato_id)[:3],
        "manutencoes_abertas": [x for x in s.manutencoes(db, contato_id)
                                if x.status != StatusManutencao.concluida],  # fmt: skip
    }


@router.get("/repasses")
@_pagina("proprietario/repasses.html", "repasses")
def repasses(request, db, ctx):
    ano = request.query_params.get("ano")
    todas = s.repasses(db, ctx["acesso"].contato_id)
    anos = sorted({x.cobranca.competencia.year for x in todas}, reverse=True)
    linhas = [x for x in todas if not ano or str(x.cobranca.competencia.year) == ano]
    return {"linhas": linhas, "anos": anos, "ano": ano or "",
            "total_liquido": round(sum(x.liquido for x in linhas), 2),
            "total_bruto": round(sum(x.bruto for x in linhas), 2)}  # fmt: skip


@router.get("/auditorias")
@_pagina("proprietario/auditorias.html", "auditorias")
def auditorias(request, db, ctx):
    return {"auditorias": s.auditorias_publicadas(db, ctx["acesso"].contato_id),
            "imoveis_todos": {i.id: i for i in s.imoveis_do(db, ctx["acesso"].contato_id)}}  # fmt: skip


@router.get("/auditorias/{auditoria_id}")
def auditoria(auditoria_id: str, request: Request, db: Db):
    try:
        ctx = _contexto(request, db, "auditorias")
        a = s.auditoria_publicada(db, ctx["acesso"].contato_id, auditoria_id)
    except _Redirecionar as r:
        return _ir(r.destino)
    except NaoEncontrado:
        return _resposta("nao_encontrado.html", _base(request, db), 404)
    ctx |= relatorio.contexto(
        db, a, lambda x: f"/proprietario/midia/{x.id}", relatorio.endereco_base(request),
        lambda x: f"/proprietario/midia/{x.id}?largura=640",
    ) | {  # fmt: skip
        "voltar": "/proprietario/auditorias", "equipe": False}
    return _resposta("auditoria/relatorio.html", ctx)


@router.get("/manutencoes")
@_pagina("proprietario/manutencoes.html", "manutencoes")
def manutencoes(request, db, ctx):
    return {"manutencoes": s.manutencoes(db, ctx["acesso"].contato_id),
            "imoveis_todos": {i.id: i for i in s.imoveis_do(db, ctx["acesso"].contato_id)}}  # fmt: skip


@router.get("/midia/{midia_id}")
def midia(midia_id: str, request: Request, db: Db,
          largura: Annotated[int | None, Query(ge=1, le=4000)] = None):  # fmt: skip
    try:
        acesso = _acesso(request, db)
        m = s.midia_publicada(db, acesso.contato_id, midia_id)
    except _Redirecionar as r:
        return _ir(r.destino)
    except NaoEncontrado:
        return Response("Arquivo não encontrado.", status_code=404)
    arquivo = db.get(Arquivo, m.arquivo_id)
    if arquivo is None or not caminho_arquivo(m.arquivo_id).is_file():
        return Response("Arquivo não encontrado.", status_code=404)
    return resposta_arquivo(arquivo, largura)

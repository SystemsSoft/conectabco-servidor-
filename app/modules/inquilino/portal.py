"""Área do inquilino no site (/inquilino). Sessão em cookie HttpOnly;
formulários com token CSRF. Cada página só mostra dados dos contratos em
que o contato logado é o locatário."""

import hmac
from datetime import datetime
from typing import Annotated
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import NaoEncontrado, RegraNegocio
from app.core.tempo import agora
from app.modules.arquivos.api import resposta_arquivo
from app.modules.crm.models import Contato, Imovel
from app.modules.financeiro.documentos import documento_do_contato, pastas_do_contato
from app.modules.inquilino import models as m
from app.modules.inquilino import services as s
from app.modules.inquilino.enums import TipoArquivoContrato
from app.modules.locacao.models import Cobranca
from app.modules.manutencao.enums import StatusManutencao, TipoManutencao
from app.modules.site.publico import _base, templates

router = APIRouter(prefix="/inquilino", include_in_schema=False)
Db = Annotated[Session, Depends(get_db)]
COOKIE = "portal_inquilino"


class _Redirecionar(Exception):
    def __init__(self, destino: str):
        self.destino = destino


def _ir(destino: str) -> RedirectResponse:
    return RedirectResponse(destino, status_code=303)


def _com_erro(destino: str, erro: str) -> RedirectResponse:
    sep = "&" if "?" in destino else "?"
    return _ir(f"{destino}{sep}{urlencode({'erro': erro})}")


def _resposta(nome: str, ctx: dict, status: int = 200) -> Response:
    if not ctx["cfg"].no_ar or not ctx["cfg"].mostrar_area_inquilino:
        return templates.TemplateResponse(ctx["request"], "manutencao.html", ctx, status_code=503)
    r = templates.TemplateResponse(ctx["request"], nome, ctx, status_code=status)
    r.headers["Cache-Control"] = "no-store"  # dados pessoais: sem cache
    r.headers["X-Frame-Options"] = "DENY"
    r.headers["X-Content-Type-Options"] = "nosniff"
    r.headers["Referrer-Policy"] = "same-origin"
    return r


def _acesso(request: Request, db: Session) -> m.AcessoInquilino:
    acesso = s.acesso_do_token(db, request.cookies.get(COOKIE))
    if acesso is None:
        raise _Redirecionar("/inquilino/entrar")
    return acesso


def _contexto(request: Request, db: Session, pagina: str, exigir_senha_nova: bool = True) -> dict:
    acesso = _acesso(request, db)
    if exigir_senha_nova and acesso.trocar_senha:
        raise _Redirecionar("/inquilino/senha")
    contratos = s.contratos_do(db, acesso)
    escolhido = request.query_params.get("c")
    atual = next((c for c in contratos if c.id == escolhido), contratos[0] if contratos else None)
    contato = db.get(Contato, acesso.contato_id)
    imoveis = {c.imovel_id: db.get(Imovel, c.imovel_id) for c in contratos}
    avisos = s.comunicados_do(db, acesso)
    sufixo = f"?c={atual.id}" if atual and len(contratos) > 1 else ""
    return _base(
        request, db,
        acesso=acesso, contato=contato, contratos=contratos, contrato=atual,
        imoveis=imoveis, imovel=imoveis.get(atual.imovel_id) if atual else None,
        nao_lidos=sum(not lido for _, lido in avisos), avisos=avisos,
        csrf=s.token_csrf(acesso), aba=pagina, sufixo=sufixo,
        pagina_atual="inquilino", hoje=agora().date(),
    )  # fmt: skip


def _conferir_csrf(acesso: m.AcessoInquilino, token: str) -> None:
    if not hmac.compare_digest(s.token_csrf(acesso), token or ""):
        raise RegraNegocio("Sessão expirada. Recarregue a página e tente de novo.")


def _pagina(nome: str, pagina: str, exigir_senha_nova: bool = True):
    """Rota GET protegida: monta o contexto ou manda para o login."""

    def decorador(funcao):
        def rota(request: Request, db: Db):
            try:
                ctx = _contexto(request, db, pagina, exigir_senha_nova)
            except _Redirecionar as r:
                return _ir(r.destino)
            if ctx["contrato"] is None and pagina not in ("senha",):
                return _resposta("inquilino/sem_contrato.html", ctx)
            extra = funcao(request, db, ctx)
            if isinstance(extra, Response):
                return extra
            return _resposta(nome, ctx | (extra or {}))

        rota.__name__ = funcao.__name__
        return rota

    return decorador


# ------------------------------------------------------------------ Login


@router.get("/entrar")
def entrar(request: Request, db: Db):
    if s.acesso_do_token(db, request.cookies.get(COOKIE)):
        return _ir("/inquilino")
    return _resposta("inquilino/entrar.html", _base(request, db, pagina_atual="inquilino"))


@router.post("/entrar")
def entrar_enviar(request: Request, db: Db, documento: Annotated[str, Form()] = "",
                  senha: Annotated[str, Form()] = ""):  # fmt: skip
    try:
        acesso = s.autenticar(db, documento, senha)
    except RegraNegocio as e:
        return _com_erro("/inquilino/entrar", e.mensagem)
    r = _ir("/inquilino/senha" if acesso.trocar_senha else "/inquilino")
    r.set_cookie(
        COOKIE, s.criar_token(acesso), max_age=s.SESSAO_HORAS * 3600, path="/inquilino",
        httponly=True, samesite="lax", secure=request.url.scheme == "https" or s.site_seguro(),
    )  # fmt: skip
    return r


@router.post("/sair")
def sair(request: Request, db: Db):
    r = _ir("/inquilino/entrar")
    r.delete_cookie(COOKIE, path="/inquilino")
    return r


@router.get("/senha")
@_pagina("inquilino/senha.html", "senha", exigir_senha_nova=False)
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
        _conferir_csrf(acesso, csrf)
        s.trocar_senha(db, acesso, atual, nova, repetida)
    except RegraNegocio as e:
        return _com_erro("/inquilino/senha", e.mensagem)
    r = _ir("/inquilino?ok=" + "Senha alterada.")
    r.set_cookie(
        COOKIE, s.criar_token(acesso), max_age=s.SESSAO_HORAS * 3600, path="/inquilino",
        httponly=True, samesite="lax", secure=request.url.scheme == "https" or s.site_seguro(),
    )  # fmt: skip
    return r


# ---------------------------------------------------------------- Páginas


@router.get("")
@_pagina("inquilino/painel.html", "inicio")
def painel(request, db, ctx):
    lista = s.parcelas(db, ctx["contrato"])
    return {
        "resumo": s.resumo_pagamentos(lista),
        "abertas": [p for p in lista if p.situacao in ("aberta", "vencida")][:3],
        "chamados_abertos": [c for c in s.chamados(db, ctx["contrato"]) if c.status != StatusManutencao.concluida],
        "ultimos_avisos": ctx["avisos"][:3],
    }  # fmt: skip


@router.get("/pagamentos")
@_pagina("inquilino/pagamentos.html", "pagamentos")
def pagamentos(request, db, ctx):
    lista = s.parcelas(db, ctx["contrato"])
    anos = sorted({p.cobranca.vencimento.year for p in lista}, reverse=True)
    ano = request.query_params.get("ano")
    pagas = [p for p in lista if p.situacao == "paga" and (not ano or str(p.cobranca.vencimento.year) == ano)]
    return {
        "resumo": s.resumo_pagamentos(lista),
        "abertas": sorted((p for p in lista if p.situacao in ("aberta", "vencida")), key=lambda p: p.cobranca.vencimento),
        "pagas": pagas, "anos": anos, "ano": ano or "",
    }  # fmt: skip


@router.get("/boleto/{cobranca_id}")
@_pagina("inquilino/boleto.html", "pagamentos")
def boleto(request, db, ctx):
    cobranca_id = request.path_params["cobranca_id"]
    p = next((p for p in s.parcelas(db, ctx["contrato"]) if p.cobranca.id == cobranca_id), None)
    if p is None:
        # Pode ser de outro contrato do mesmo inquilino.
        for c in ctx["contratos"]:
            p = next((x for x in s.parcelas(db, c) if x.cobranca.id == cobranca_id), None)
            if p:
                ctx["contrato"], ctx["imovel"] = c, ctx["imoveis"][c.imovel_id]
                break
    if p is None or p.situacao == "cancelada":
        return _resposta("nao_encontrado.html", ctx, 404)
    from app.modules.personalizacao.models import DadosEmpresa

    e = db.get(DadosEmpresa, 1)
    chave = e.chave_pix if e else ""
    pix = None
    if chave and p.situacao != "paga":
        cidade = s.cidade_da_empresa(e.endereco if e else "", ctx["imovel"].cidade if ctx["imovel"] else "")
        pix = s.pix_copia_e_cola(
            chave, ctx["empresa"]["nome"], cidade or "BRASIL", p.estimativa or p.total,
            f"{ctx['contrato'].numero}{p.cobranca.competencia:%m%Y}",
        )  # fmt: skip
    return {"p": p, "pix": pix, "chave_pix": chave}


@router.get("/documentos")
@_pagina("inquilino/documentos.html", "documentos")
def documentos(request, db, ctx):
    todos = s.arquivos_visiveis(db, ctx["contrato"])
    grupos = {
        "contrato": [a for a in todos if a.tipo == TipoArquivoContrato.contrato],
        "vistoria": [a for a in todos if a.tipo == TipoArquivoContrato.vistoria],
        "documento": [a for a in todos if a.tipo == TipoArquivoContrato.documento],
        "enviados": [a for a in todos if a.tipo == TipoArquivoContrato.estadoImovel],
    }
    return {"grupos": grupos, "categorias": s.categorias(db, grupos["enviados"]),
            "pastas": pastas_do_contato(db, ctx["acesso"].contato_id)}  # fmt: skip


@router.get("/documento/{id}")
def documento_compartilhado(id: str, request: Request, db: Db):
    """Documento de uma pasta do Financeiro compartilhada com o inquilino."""
    try:
        acesso = _acesso(request, db)
        a = documento_do_contato(db, acesso.contato_id, id)
    except _Redirecionar as r:
        return _ir(r.destino)
    except NaoEncontrado:
        return Response("Arquivo não encontrado.", status_code=404)
    return resposta_arquivo(a)


@router.post("/documentos")
async def documentos_enviar(request: Request, db: Db, descricao: Annotated[str, Form()] = "",
                            csrf: Annotated[str, Form()] = "", c: Annotated[str, Form()] = "",
                            arquivos: Annotated[list[UploadFile], File()] = []):  # fmt: skip
    destino = "/inquilino/documentos" + (f"?c={c}" if c else "")
    try:
        acesso = _acesso(request, db)
        _conferir_csrf(acesso, csrf)
        contrato = s.contrato_do(db, acesso, c or None)
        s.enviar_estado_imovel(db, contrato, descricao, [(a.filename, a.file) for a in arquivos])
    except _Redirecionar as r:
        return _ir(r.destino)
    except RegraNegocio as e:
        return _com_erro(destino, e.mensagem)
    return _ir(destino + ("&" if c else "?") + "ok=Arquivos enviados à imobiliária.")


@router.get("/arquivo/{id}")
def arquivo(id: str, request: Request, db: Db):
    try:
        acesso = _acesso(request, db)
        a, caminho, mime, nome = s.arquivo_do_inquilino(db, acesso, id)
    except _Redirecionar as r:
        return _ir(r.destino)
    except NaoEncontrado:
        return Response("Arquivo não encontrado.", status_code=404)
    inline = mime.startswith(("image/", "video/", "application/pdf"))
    return FileResponse(
        caminho, media_type=mime, filename=nome,
        content_disposition_type="inline" if inline else "attachment",
        headers={"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"},
    )  # fmt: skip


@router.get("/chamados")
@_pagina("inquilino/chamados.html", "chamados")
def chamados(request, db, ctx):
    lista = s.chamados(db, ctx["contrato"])
    anexos = {c.id: [a for a in s.anexos_do_chamado(db, c.id) if a.visivel_inquilino] for c in lista}
    todos = [a for itens in anexos.values() for a in itens]
    return {"chamados": lista, "anexos": anexos, "tipos": TipoManutencao, "categorias": s.categorias(db, todos)}


@router.post("/chamados")
async def chamados_abrir(request: Request, db: Db, tipo: Annotated[str, Form()] = "outros",
                         descricao: Annotated[str, Form()] = "", csrf: Annotated[str, Form()] = "",
                         c: Annotated[str, Form()] = "",
                         arquivos: Annotated[list[UploadFile], File()] = []):  # fmt: skip
    destino = "/inquilino/chamados" + (f"?c={c}" if c else "")
    try:
        acesso = _acesso(request, db)
        _conferir_csrf(acesso, csrf)
        contrato = s.contrato_do(db, acesso, c or None)
        s.abrir_chamado(db, contrato, tipo, descricao, [(a.filename, a.file) for a in arquivos])
    except _Redirecionar as r:
        return _ir(r.destino)
    except RegraNegocio as e:
        return _com_erro(destino, e.mensagem)
    return _ir(destino + ("&" if c else "?") + "ok=Chamado aberto. A imobiliária já foi avisada.")


@router.get("/avisos")
@_pagina("inquilino/avisos.html", "avisos")
def avisos(request, db, ctx):
    s.marcar_lidos(db, ctx["acesso"], [c for c, lido in ctx["avisos"] if not lido])
    return {"agora": datetime.now()}

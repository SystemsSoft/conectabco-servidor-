"""Relatório da auditoria (HTML imprimível): checklist, fotos, vídeos com o
que foi dito (transcrição), nota e recomendações. O mesmo relatório serve à
equipe (link assinado, sem login) e ao proprietário (Área do proprietário).

Cada foto e vídeo leva um QR code para um link próprio (sem login e sem
validade, como um link de compartilhamento), que abre a mídia no celular
mesmo com o relatório impresso."""

import time
from collections.abc import Callable
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from markupsafe import Markup
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.seguranca import assinar, assinatura_valida
from app.modules.arquivos.api import resposta_arquivo
from app.modules.arquivos.models import Arquivo
from app.modules.arquivos.services import link as link_arquivo
from app.modules.auditoria import models as m
from app.modules.auditoria.enums import EstadoItem, StatusTranscricao
from app.modules.crm.models import Contato, Imovel
from app.modules.locacao.models import ContratoLocacao

router = APIRouter(include_in_schema=False)
Db = Annotated[Session, Depends(get_db)]


def link(auditoria_id: str) -> str:
    expira = int(time.time()) + get_settings().token_horas * 3600
    return f"/relatorio-auditoria/{auditoria_id}?expira={expira}&assinatura={assinar(f'relatorio:{auditoria_id}:{expira}')}"


def token_midia(midia_id: str) -> str:
    return assinar(f"midia-publica:{midia_id}")


def endereco_base(request: Request) -> str:
    base = get_settings().site_url or str(request.base_url)
    return base if base.endswith("/") else base + "/"


def link_publico(base: str, midia_id: str) -> str:
    """Link de compartilhamento da mídia (o do QR code)."""
    return f"{base}auditoria/midia/{midia_id}?t={token_midia(midia_id)}"


@lru_cache(maxsize=512)
def qr_svg(texto: str) -> Markup:
    import segno

    svg = segno.make(texto, error="m").svg_inline(scale=3, border=2, dark="#061A48", light="#ffffff")
    return Markup(svg)


def contexto(db: Session, a: m.Auditoria, url_midia: Callable[[m.MidiaAuditoria], str],
             base: str, url_miniatura: Callable[[m.MidiaAuditoria], str] | None = None) -> dict:  # fmt: skip
    """Dados do relatório; `url_midia` diz como cada foto/vídeo é aberto e
    `url_miniatura` a versão leve da foto exibida na página."""
    from app.modules.equipe.models import Usuario

    imovel = db.get(Imovel, a.imovel_id)
    contrato = db.get(ContratoLocacao, a.contrato_id) if a.contrato_id else None
    proprietario = db.get(Contato, a.proprietario_id) if a.proprietario_id else None
    corretor = db.get(Usuario, a.corretor_id) if a.corretor_id else None
    areas: dict[str, list] = {}
    for i in a.itens:
        areas.setdefault(i.area, []).append(i)
    fotos = [x for x in a.midias if x.tipo.value == "foto"]
    videos = [x for x in a.midias if x.tipo.value == "video"]
    return {
        "a": a, "imovel": imovel, "contrato": contrato, "proprietario": proprietario,
        "corretor": corretor, "areas": areas, "fotos": fotos, "videos": videos,
        "url_midia": url_midia, "url_miniatura": url_miniatura or url_midia,
        "url_publica": lambda x: link_publico(base, x.id),
        "qr": lambda x: qr_svg(link_publico(base, x.id)),
        "Estado": EstadoItem, "Transcricao": StatusTranscricao,
        "contagem": {e: sum(i.estado == e for i in a.itens) for e in EstadoItem},
        "itens_por_id": {i.id: i for i in a.itens},
    }  # fmt: skip


@router.get("/relatorio-auditoria/{auditoria_id}")
def relatorio_equipe(auditoria_id: str, expira: int, assinatura: str, request: Request, db: Db):
    from app.modules.site.publico import _base, templates

    a = db.get(m.Auditoria, auditoria_id)
    ok = expira >= time.time() and assinatura_valida(f"relatorio:{auditoria_id}:{expira}", assinatura)
    if a is None or not ok:
        return Response("Link expirado ou inválido.", status_code=404)
    ctx = _base(request, db) | contexto(
        db, a, lambda x: link_arquivo(x.arquivo_id), endereco_base(request),
        lambda x: link_arquivo(x.arquivo_id) + "&largura=640",
    ) | {"voltar": None, "equipe": True}  # fmt: skip
    resposta = templates.TemplateResponse(request, "auditoria/relatorio.html", ctx)
    resposta.headers["Cache-Control"] = "no-store"
    resposta.headers["X-Robots-Tag"] = "noindex"
    return resposta


# ------------------------------------------------- Mídia pelo QR code


def _midia_publica(db: Session, midia_id: str, t: str) -> m.MidiaAuditoria | None:
    midia = db.get(m.MidiaAuditoria, midia_id)
    if midia is None or not assinatura_valida(f"midia-publica:{midia_id}", t):
        return None
    return midia


@router.get("/auditoria/midia/{midia_id}")
def midia_publica(midia_id: str, request: Request, db: Db, t: str = ""):
    """Página aberta pelo QR code do relatório: a foto ou o vídeo (com a
    transcrição), no celular, sem login."""
    from app.modules.site.publico import _base, templates

    midia = _midia_publica(db, midia_id, t)
    if midia is None:
        return Response("Link inválido ou mídia removida.", status_code=404)
    a = db.get(m.Auditoria, midia.auditoria_id)
    item = next((i for i in a.itens if i.id == midia.item_id), None)
    arquivo = f"/auditoria/midia/{midia.id}/arquivo?t={t}"
    ctx = _base(request, db) | {
        "a": a, "midia": midia, "item": item, "imovel": db.get(Imovel, a.imovel_id),
        "arquivo": arquivo, "Transcricao": StatusTranscricao,
    }  # fmt: skip
    resposta = templates.TemplateResponse(request, "auditoria/midia.html", ctx)
    resposta.headers["Cache-Control"] = "no-store"
    resposta.headers["X-Robots-Tag"] = "noindex"
    resposta.headers["Referrer-Policy"] = "no-referrer"
    return resposta


@router.get("/auditoria/midia/{midia_id}/arquivo")
def midia_publica_arquivo(
    midia_id: str, db: Db, t: str = "",
    largura: Annotated[int | None, Query(ge=1, le=4000)] = None,
):  # fmt: skip
    midia = _midia_publica(db, midia_id, t)
    arquivo = db.get(Arquivo, midia.arquivo_id) if midia else None
    if arquivo is None:
        return Response("Link inválido ou mídia removida.", status_code=404)
    resposta = resposta_arquivo(arquivo, largura)
    resposta.headers["X-Robots-Tag"] = "noindex"
    return resposta

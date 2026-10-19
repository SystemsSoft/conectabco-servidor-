"""Relatório da auditoria (HTML imprimível): checklist, fotos, vídeos com o
que foi dito (transcrição), nota e recomendações. O mesmo relatório serve à
equipe (link assinado, sem login) e ao proprietário (Área do proprietário)."""

import time
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.seguranca import assinar, assinatura_valida
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


def contexto(db: Session, a: m.Auditoria, url_midia: Callable[[m.MidiaAuditoria], str]) -> dict:
    """Dados do relatório; `url_midia` diz como cada foto/vídeo é aberto."""
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
        "url_midia": url_midia, "Estado": EstadoItem, "Transcricao": StatusTranscricao,
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
        db, a, lambda x: link_arquivo(x.arquivo_id)
    ) | {"voltar": None, "equipe": True}
    resposta = templates.TemplateResponse(request, "auditoria/relatorio.html", ctx)
    resposta.headers["Cache-Control"] = "no-store"
    resposta.headers["X-Robots-Tag"] = "noindex"
    return resposta

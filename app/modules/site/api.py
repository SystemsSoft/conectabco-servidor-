"""Gestão do site (app): configuração e caixa de leads."""

from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import NaoEncontrado, validar_id
from app.core.schemas import Pagina, pagina
from app.modules.site import models as m
from app.modules.site import schemas as s
from app.modules.site import services
from app.modules.site.enums import StatusLead

router = APIRouter(prefix="/site", tags=["Site e Leads"])
Db = Annotated[Session, Depends(get_db)]


@router.get("/configuracao", response_model=s.ConfiguracaoSite)
def obter_configuracao(db: Db):
    return services.configuracao(db)


@router.put("/configuracao", response_model=s.ConfiguracaoSite)
def salvar_configuracao(dados: s.ConfiguracaoSite, db: Db):
    return services.salvar_configuracao(db, dados)


@router.get("/leads", response_model=Pagina[s.LeadSaida])
def listar_leads(
    db: Db,
    status: StatusLead | None = None,
    limite: Annotated[int, Query(ge=1, le=500)] = 100,
    deslocamento: Annotated[int, Query(ge=0)] = 0,
):
    filtro = [m.LeadSite.status == status] if status else []
    total = db.scalar(sa.select(sa.func.count()).select_from(m.LeadSite).where(*filtro))
    itens = db.scalars(
        sa.select(m.LeadSite)
        .where(*filtro)
        .order_by(m.LeadSite.criado_em.desc(), m.LeadSite.id)
        .limit(limite)
        .offset(deslocamento)
    ).all()
    return pagina([s.LeadSaida.model_validate(i) for i in itens], total, limite, deslocamento)


def _lead(db: Session, id: str) -> m.LeadSite:
    lead = db.get(m.LeadSite, validar_id(id))
    if lead is None:
        raise NaoEncontrado("Lead não encontrado.")
    return lead


@router.put("/leads/{id}", response_model=s.LeadSaida)
def atualizar_lead(id: str, dados: s.LeadAtualizacao, db: Db):
    return services.atualizar_lead(db, _lead(db, id), dados)


@router.delete("/leads/{id}", status_code=204)
def remover_lead(id: str, db: Db):
    db.delete(_lead(db, id))
    db.commit()
    return Response(status_code=204)

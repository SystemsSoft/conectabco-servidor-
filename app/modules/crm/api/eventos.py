from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.schemas import Pagina
from app.modules.crm.enums import TipoEvento
from app.modules.crm.schemas import EventoEntrada, EventoSaida
from app.modules.crm.services import EventoService

router = APIRouter(prefix="/eventos", tags=["CRM • Central de Relacionamento"])


def _service(db: Annotated[Session, Depends(get_db)]) -> EventoService:
    return EventoService(db)


Service = Annotated[EventoService, Depends(_service)]


@router.get("", response_model=Pagina[EventoSaida])
def listar(
    svc: Service,
    contato_id: str | None = Query(None, alias="contatoId"),
    imovel_id: str | None = Query(None, alias="imovelId"),
    tipo: TipoEvento | None = None,
    concluido: bool | None = None,
    de: datetime | None = Query(None, description="Data/hora inicial (inclusive)"),
    ate: datetime | None = Query(None, description="Data/hora final (exclusive)"),
    limite: int = Query(100, ge=1, le=500),
    deslocamento: int = Query(0, ge=0),
):
    return svc.listar(
        limite,
        deslocamento,
        contato_id=contato_id,
        imovel_id=imovel_id,
        tipo=tipo,
        concluido=concluido,
        de=de,
        ate=ate,
    )


@router.get("/pendentes", response_model=list[EventoSaida])
def pendentes(svc: Service):
    """Compromissos atrasados ou de hoje ainda não concluídos."""
    return svc.pendentes()


@router.get("/{id}", response_model=EventoSaida)
def obter(id: str, svc: Service):
    return svc.obter(id)


@router.post("", response_model=EventoSaida, status_code=status.HTTP_201_CREATED)
def criar(dados: EventoEntrada, svc: Service):
    return svc.criar(dados)


@router.put("/{id}", response_model=EventoSaida)
def atualizar(id: str, dados: EventoEntrada, svc: Service):
    return svc.atualizar(id, dados)


@router.post("/{id}/alternar-conclusao", response_model=EventoSaida)
def alternar_conclusao(id: str, svc: Service):
    return svc.alternar_conclusao(id)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def remover(id: str, svc: Service) -> None:
    svc.remover(id)

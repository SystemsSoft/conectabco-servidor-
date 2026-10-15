from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.core.database import get_db
from app.modules.locacao.schemas import RepasseEntrada, RepasseSaida
from app.modules.locacao.services import RepasseService

router = APIRouter(prefix="/repasses", tags=["Locação • Repasses"])
Service = Annotated[RepasseService, Depends(lambda db=Depends(get_db): RepasseService(db))]


@router.get("", response_model=list[RepasseSaida])
def listar(svc: Service, cobranca_id: str | None = Query(None, alias="cobrancaId")):
    """Repasses já feitos (cobrança + beneficiário + data)."""
    return svc.listar(cobranca_id)


@router.put("/{cobranca_id}/{contato_id}", response_model=RepasseSaida)
def marcar(cobranca_id: str, contato_id: str, dados: RepasseEntrada, svc: Service):
    """Marca o repasse da cobrança ao beneficiário como feito na data."""
    return svc.marcar(cobranca_id, contato_id, dados)


@router.delete("/{cobranca_id}/{contato_id}", status_code=status.HTTP_204_NO_CONTENT)
def desmarcar(cobranca_id: str, contato_id: str, svc: Service) -> None:
    svc.desmarcar(cobranca_id, contato_id)

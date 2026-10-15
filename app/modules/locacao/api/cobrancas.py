from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.database import get_db
from app.core.schemas import Pagina
from app.modules.locacao.enums import StatusCobranca
from app.modules.locacao.schemas import CobrancaEntrada, CobrancaSaida
from app.modules.locacao.services import CobrancaService

router = APIRouter(prefix="/cobrancas", tags=["Locação • Boletos e recibos"])
Service = Annotated[CobrancaService, Depends(lambda db=Depends(get_db): CobrancaService(db))]


@router.get("", response_model=Pagina[CobrancaSaida])
def listar(
    svc: Service,
    contrato_id: str | None = Query(None, alias="contratoId"),
    competencia: date | None = Query(None, description="Primeiro dia do mês"),
    status_: StatusCobranca | None = Query(None, alias="status"),
    limite: int = Query(100, ge=1, le=500),
    deslocamento: int = Query(0, ge=0),
):
    return svc.listar(
        limite, deslocamento, contrato_id=contrato_id,
        competencia=competencia, status=status_,
    )  # fmt: skip


@router.get("/{id}", response_model=CobrancaSaida)
def obter(id: str, svc: Service):
    return svc.obter(id)


@router.put("/{id}", response_model=CobrancaSaida)
def salvar(id: str, dados: CobrancaEntrada, svc: Service, response: Response):
    """Grava a cobrança (gerada no app) com pagamento, encargos e itens."""
    salvo, criado = svc.salvar(id, dados)
    if criado:
        response.status_code = status.HTTP_201_CREATED
    return salvo


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def remover(id: str, svc: Service) -> None:
    svc.remover(id)

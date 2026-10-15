from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.database import get_db
from app.core.schemas import Pagina
from app.modules.locacao.schemas import DespesaEntrada, DespesaSaida
from app.modules.locacao.services import DespesaService

router = APIRouter(prefix="/despesas", tags=["Locação • Despesas"])
Service = Annotated[DespesaService, Depends(lambda db=Depends(get_db): DespesaService(db))]


@router.get("", response_model=Pagina[DespesaSaida])
def listar(
    svc: Service,
    contrato_id: str | None = Query(None, alias="contratoId"),
    limite: int = Query(100, ge=1, le=500),
    deslocamento: int = Query(0, ge=0),
):
    return svc.listar(limite, deslocamento, contrato_id=contrato_id)


@router.put("/{id}", response_model=DespesaSaida)
def salvar(id: str, dados: DespesaEntrada, svc: Service, response: Response):
    salvo, criado = svc.salvar(id, dados)
    if criado:
        response.status_code = status.HTTP_201_CREATED
    return salvo


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def remover(id: str, svc: Service) -> None:
    svc.remover(id)

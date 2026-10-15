from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.schemas import Pagina
from app.modules.locacao.enums import StatusContrato
from app.modules.locacao.schemas import ContratoEntrada, ContratoSaida
from app.modules.locacao.services import ContratoService

router = APIRouter(prefix="/contratos", tags=["Locação • Contratos"])
Service = Annotated[ContratoService, Depends(lambda db=Depends(get_db): ContratoService(db))]


@router.get("", response_model=Pagina[ContratoSaida])
def listar(
    svc: Service,
    status_: StatusContrato | None = Query(None, alias="status"),
    imovel_id: str | None = Query(None, alias="imovelId"),
    locatario_id: str | None = Query(None, alias="locatarioId"),
    busca: str | None = Query(None, description="Número do contrato"),
    limite: int = Query(100, ge=1, le=500),
    deslocamento: int = Query(0, ge=0),
):
    return svc.listar(
        limite, deslocamento, status=status_, imovel_id=imovel_id,
        locatario_id=locatario_id, busca=busca,
    )  # fmt: skip


@router.get("/{id}", response_model=ContratoSaida)
def obter(id: str, svc: Service):
    return svc.obter(id)


@router.put("/{id}", response_model=ContratoSaida)
def salvar(id: str, dados: ContratoEntrada, svc: Service, response: Response):
    """Atualiza; se o id (UUID do app) é novo, cria com número LOC-0001... (201)."""
    salvo, criado = svc.salvar(id, dados)
    if criado:
        response.status_code = status.HTTP_201_CREATED
    return salvo


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def remover(id: str, svc: Service) -> None:
    """Remove o contrato junto com despesas, cobranças e repasses."""
    svc.remover(id)

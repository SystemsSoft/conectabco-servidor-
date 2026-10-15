from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.database import get_db
from app.core.schemas import Pagina
from app.modules.vendas.enums import StatusParcela, StatusVenda
from app.modules.vendas.schemas import (
    ParcelaEntrada,
    ParcelaLote,
    ParcelaSaida,
    VendaEntrada,
    VendaSaida,
)
from app.modules.vendas.services import ParcelaService, VendaService

router = APIRouter(prefix="/vendas")
Vendas = Annotated[VendaService, Depends(lambda db=Depends(get_db): VendaService(db))]
Parcelas = Annotated[
    ParcelaService, Depends(lambda db=Depends(get_db): ParcelaService(db))
]

# As rotas de /parcelas vêm antes de /{id} para não serem confundidas.

_p = APIRouter(prefix="/parcelas", tags=["Vendas • Parcelas"])


@_p.get("", response_model=Pagina[ParcelaSaida])
def listar_parcelas(
    svc: Parcelas,
    venda_id: str | None = Query(None, alias="vendaId"),
    status_: StatusParcela | None = Query(None, alias="status"),
    limite: int = Query(100, ge=1, le=500),
    deslocamento: int = Query(0, ge=0),
):
    return svc.listar(limite, deslocamento, venda_id=venda_id, status=status_)


@_p.put("", response_model=list[ParcelaSaida])
def salvar_lote(lote: list[ParcelaLote], svc: Parcelas):
    """Grava várias parcelas de uma vez (tabela do financiamento próprio)."""
    return svc.salvar_lote(lote)


@_p.put("/{id}", response_model=ParcelaSaida)
def salvar_parcela(id: str, dados: ParcelaEntrada, svc: Parcelas, response: Response):
    """Grava a parcela (ex.: pagamento com multa e juros calculados no app)."""
    salvo, criado = svc.salvar(id, dados)
    if criado:
        response.status_code = status.HTTP_201_CREATED
    return salvo


router.include_router(_p)

@router.get(tags=["Vendas"], path="", response_model=Pagina[VendaSaida])
def listar(
    svc: Vendas,
    status_: StatusVenda | None = Query(None, alias="status"),
    imovel_id: str | None = Query(None, alias="imovelId"),
    busca: str | None = Query(None, description="Número da venda"),
    limite: int = Query(100, ge=1, le=500),
    deslocamento: int = Query(0, ge=0),
):
    return svc.listar(
        limite, deslocamento, status=status_, imovel_id=imovel_id, busca=busca
    )


@router.get(tags=["Vendas"], path="/{id}", response_model=VendaSaida)
def obter(id: str, svc: Vendas):
    return svc.obter(id)


@router.put(tags=["Vendas"], path="/{id}", response_model=VendaSaida)
def salvar(id: str, dados: VendaEntrada, svc: Vendas, response: Response):
    """Atualiza; se o id (UUID do app) é novo, cria com número VEN-0001... (201)."""
    salvo, criado = svc.salvar(id, dados)
    if criado:
        response.status_code = status.HTTP_201_CREATED
    return salvo


@router.delete(tags=["Vendas"], path="/{id}", status_code=status.HTTP_204_NO_CONTENT)
def remover(id: str, svc: Vendas) -> None:
    """Remove a venda com as parcelas."""
    svc.remover(id)


@router.delete(tags=["Vendas"], path="/{id}/parcelas", status_code=status.HTTP_204_NO_CONTENT)
def remover_parcelas(id: str, svc: Parcelas) -> None:
    """Apaga as parcelas da venda (antes de gerar uma nova tabela)."""
    svc.remover_da_venda(id)


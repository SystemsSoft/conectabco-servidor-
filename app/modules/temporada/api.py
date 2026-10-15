from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.database import get_db
from app.core.schemas import Pagina
from app.modules.temporada.enums import SituacaoReserva
from app.modules.temporada.schemas import ReservaEntrada, ReservaSaida
from app.modules.temporada.services import ReservaService

router = APIRouter(prefix="/temporada", tags=["Locação por Temporada"])
Service = Annotated[ReservaService, Depends(lambda db=Depends(get_db): ReservaService(db))]


@router.get("/reservas", response_model=Pagina[ReservaSaida])
def listar(
    svc: Service,
    imovel_id: str | None = Query(None, alias="imovelId"),
    situacao: SituacaoReserva | None = None,
    de: date | None = Query(None, description="Ocupa alguma noite a partir de"),
    ate: date | None = Query(None, description="Começa antes de"),
    limite: int = Query(100, ge=1, le=500),
    deslocamento: int = Query(0, ge=0),
):
    return svc.listar(
        limite, deslocamento, imovel_id=imovel_id, situacao=situacao, de=de, ate=ate
    )


@router.get("/disponibilidade", response_model=list[ReservaSaida])
def disponibilidade(
    svc: Service,
    imovel_id: str = Query(alias="imovelId"),
    check_in: date = Query(alias="checkIn"),
    check_out: date = Query(alias="checkOut"),
    ignorar_id: str | None = Query(None, alias="ignorarId"),
):
    """Reservas que impedem o período (lista vazia = livre)."""
    return svc.conflitos(imovel_id, check_in, check_out, ignorar_id)


@router.get("/reservas/{id}", response_model=ReservaSaida)
def obter(id: str, svc: Service):
    return svc.obter(id)


@router.put("/reservas/{id}", response_model=ReservaSaida)
def salvar(id: str, dados: ReservaEntrada, svc: Service, response: Response):
    """Grava; se o id (UUID do app) é novo, cria com número RES-0001... (201).
    Recusa datas sobrepostas a outra reserva ativa do mesmo imóvel."""
    salvo, criado = svc.salvar(id, dados)
    if criado:
        response.status_code = status.HTTP_201_CREATED
    return salvo


@router.delete("/reservas/{id}", status_code=status.HTTP_204_NO_CONTENT)
def remover(id: str, svc: Service) -> None:
    svc.remover(id)

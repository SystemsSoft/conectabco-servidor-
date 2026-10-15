from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.database import get_db
from app.core.schemas import Pagina
from app.modules.manutencao.enums import ContextoManutencao, StatusManutencao
from app.modules.manutencao.schemas import ManutencaoEntrada, ManutencaoSaida
from app.modules.manutencao.services import ManutencaoService

router = APIRouter(prefix="/manutencoes", tags=["Manutenção"])
Service = Annotated[
    ManutencaoService, Depends(lambda db=Depends(get_db): ManutencaoService(db))
]


@router.get("", response_model=Pagina[ManutencaoSaida])
def listar(
    svc: Service,
    contexto: ContextoManutencao | None = None,
    imovel_id: str | None = Query(None, alias="imovelId"),
    status_: StatusManutencao | None = Query(None, alias="status"),
    limite: int = Query(100, ge=1, le=500),
    deslocamento: int = Query(0, ge=0),
):
    return svc.listar(limite, deslocamento, contexto, imovel_id, status_)


@router.get("/{id}", response_model=ManutencaoSaida)
def obter(id: str, svc: Service):
    return svc.obter(id)


@router.put("/{id}", response_model=ManutencaoSaida)
def salvar(id: str, dados: ManutencaoEntrada, svc: Service, response: Response):
    """Grava a pauta e o diário completo; cria (201) se o id é novo."""
    salvo, criado = svc.salvar(id, dados)
    if criado:
        response.status_code = status.HTTP_201_CREATED
    return salvo


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def remover(id: str, svc: Service) -> None:
    svc.remover(id)

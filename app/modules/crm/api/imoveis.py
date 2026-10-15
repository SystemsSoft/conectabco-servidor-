from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.schemas import Pagina
from app.modules.crm.enums import Finalidade, StatusImovel, TipoImovel
from app.modules.crm.schemas import ImovelEntrada, ImovelSaida
from app.modules.crm.services import ImovelService

router = APIRouter(prefix="/imoveis", tags=["CRM • Imóveis"])


def _service(db: Annotated[Session, Depends(get_db)]) -> ImovelService:
    return ImovelService(db)


Service = Annotated[ImovelService, Depends(_service)]


@router.get("", response_model=Pagina[ImovelSaida])
def listar(
    svc: Service,
    busca: str | None = Query(None, description="Código, título, endereço ou condomínio"),
    finalidade: Finalidade | None = None,
    status_: StatusImovel | None = Query(None, alias="status"),
    tipo: TipoImovel | None = None,
    cidade: str | None = None,
    proprietario_id: str | None = Query(None, alias="proprietarioId"),
    limite: int = Query(100, ge=1, le=500),
    deslocamento: int = Query(0, ge=0),
):
    return svc.listar(
        limite,
        deslocamento,
        busca=busca,
        finalidade=finalidade,
        status=status_,
        tipo=tipo,
        cidade=cidade,
        proprietario_id=proprietario_id,
    )


@router.get("/{id}", response_model=ImovelSaida)
def obter(id: str, svc: Service):
    return svc.obter(id)


@router.post("", response_model=ImovelSaida, status_code=status.HTTP_201_CREATED)
def criar(dados: ImovelEntrada, svc: Service):
    """Cadastra o imóvel; o código sequencial (IM-0001...) é gerado aqui."""
    return svc.criar(dados)


@router.put("/{id}", response_model=ImovelSaida)
def salvar(id: str, dados: ImovelEntrada, svc: Service, response: Response):
    """Atualiza; se o id (UUID gerado pelo app) ainda não existe, cria (201)."""
    salvo, criado = svc.salvar(id, dados)
    if criado:
        response.status_code = status.HTTP_201_CREATED
    return salvo


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def remover(id: str, svc: Service) -> None:
    svc.remover(id)

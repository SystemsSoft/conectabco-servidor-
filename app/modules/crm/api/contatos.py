from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.schemas import Pagina
from app.modules.crm.enums import EtapaFunil, OrigemContato, PapelContato
from app.modules.crm.schemas import ContatoEntrada, ContatoSaida
from app.modules.crm.services import ContatoService

router = APIRouter(prefix="/contatos", tags=["CRM • Contatos"])


def _service(db: Annotated[Session, Depends(get_db)]) -> ContatoService:
    return ContatoService(db)


Service = Annotated[ContatoService, Depends(_service)]


@router.get("", response_model=Pagina[ContatoSaida])
def listar(
    svc: Service,
    busca: str | None = Query(None, description="Nome, e-mail, documento ou telefone"),
    papel: PapelContato | None = None,
    etapa: EtapaFunil | None = None,
    origem: OrigemContato | None = None,
    com_perfil: bool | None = Query(None, alias="comPerfil"),
    limite: int = Query(100, ge=1, le=500),
    deslocamento: int = Query(0, ge=0),
):
    return svc.listar(
        limite,
        deslocamento,
        busca=busca,
        papel=papel,
        etapa=etapa,
        origem=origem,
        com_perfil=com_perfil,
    )


@router.get("/{id}", response_model=ContatoSaida)
def obter(id: str, svc: Service):
    return svc.obter(id)


@router.post("", response_model=ContatoSaida, status_code=status.HTTP_201_CREATED)
def criar(dados: ContatoEntrada, svc: Service):
    return svc.criar(dados)


@router.put("/{id}", response_model=ContatoSaida)
def atualizar(id: str, dados: ContatoEntrada, svc: Service):
    return svc.atualizar(id, dados)


@router.delete("/{id}", status_code=status.HTTP_204_NO_CONTENT)
def remover(id: str, svc: Service) -> None:
    """Remove o contato; agenda e imóveis vinculados ficam sem o vínculo."""
    svc.remover(id)

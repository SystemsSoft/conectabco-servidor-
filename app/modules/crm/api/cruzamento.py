from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.modules.crm.schemas import ResumoCruzamento, Sugestao
from app.modules.crm.services import CruzamentoService

router = APIRouter(prefix="/cruzamento", tags=["CRM • Cruzamento de perfil"])


def _service(db: Annotated[Session, Depends(get_db)]) -> CruzamentoService:
    return CruzamentoService(db)


Service = Annotated[CruzamentoService, Depends(_service)]


@router.get("/resumo", response_model=ResumoCruzamento)
def resumo(svc: Service):
    return svc.resumo()


@router.get("/contatos/{contato_id}", response_model=list[Sugestao])
def imoveis_para_contato(contato_id: str, svc: Service):
    """Imóveis disponíveis compatíveis com o perfil do contato (score ≥ 50)."""
    return svc.para_contato(contato_id)


@router.get("/imoveis/{imovel_id}", response_model=list[Sugestao])
def contatos_para_imovel(imovel_id: str, svc: Service):
    """Contatos cujo perfil de interesse combina com o imóvel (score ≥ 50)."""
    return svc.para_imovel(imovel_id)

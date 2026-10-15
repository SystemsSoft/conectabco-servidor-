from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.documentos import validar_cpf, validar_cpf_cnpj
from app.core.errors import RegraNegocio
from app.core.schemas import Esquema
from app.modules.fiscal.models import DeclaranteDimob

router = APIRouter(prefix="/fiscal", tags=["Fiscal"])
Db = Annotated[Session, Depends(get_db)]


class Declarante(Esquema):
    documento: Annotated[str, Field(max_length=18)] = Field(
        "", description="CNPJ ou CPF do declarante"
    )
    nome: Annotated[str, Field(max_length=200)] = "Marcelo Bonifácio"
    responsavel_nome: Annotated[str, Field(max_length=200)] = ""
    responsavel_cpf: Annotated[str, Field(max_length=14)] = ""
    retificadora: bool = False
    numero_recibo: Annotated[str, Field(max_length=30)] = ""


@router.get("/declarante", response_model=Declarante)
def obter_declarante(db: Db):
    """Dados do declarante da DIMOB (padrão até ser salvo)."""
    d = db.get(DeclaranteDimob, 1)
    return Declarante.model_validate(d) if d else Declarante()


@router.put("/declarante", response_model=Declarante)
def salvar_declarante(dados: Declarante, db: Db):
    if not dados.nome.strip():
        raise RegraNegocio("Informe o nome do declarante.")
    if dados.documento and not validar_cpf_cnpj(dados.documento):
        raise RegraNegocio("CNPJ/CPF do declarante inválido.")
    if dados.responsavel_cpf and not validar_cpf(dados.responsavel_cpf):
        raise RegraNegocio("CPF do responsável inválido.")
    d = db.get(DeclaranteDimob, 1)
    if d is None:
        d = DeclaranteDimob(id=1)
        db.add(d)
    for campo, valor in dados.model_dump().items():
        setattr(d, campo, valor)
    db.commit()
    return Declarante.model_validate(d)

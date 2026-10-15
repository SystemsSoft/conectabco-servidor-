import re
from typing import Annotated, Literal

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Response, status
from pydantic import Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import NaoEncontrado, RegraNegocio, validar_id
from app.core.schemas import Esquema
from app.modules.contratos.models import ModeloContrato, TipoModelo

router = APIRouter(prefix="/contratos", tags=["Contratos e Relatórios"])
Db = Annotated[Session, Depends(get_db)]

# Tipos usados na impressão dos contratos de locação e de venda.
_ESSENCIAIS = {TipoModelo.locacao, TipoModelo.venda}
_CHAVE = re.compile(r"^[a-z0-9_]+$")


class Parametro(Esquema):
    chave: Annotated[str, Field(max_length=60)]
    rotulo: Annotated[str, Field(max_length=150)]
    tipo: Literal["texto", "numero", "dinheiro", "data"] = "texto"
    valor_padrao: str = ""
    descricao: str = ""


class ModeloEntrada(Esquema):
    nome: Annotated[str, Field(max_length=150)]
    tipo: TipoModelo
    texto: str
    descricao: str = ""
    parametros: list[Parametro] = []
    base_id: Annotated[str, Field(max_length=100)] | None = None


class ModeloSaida(ModeloEntrada):
    id: str
    atualizado_em: str


def _saida(m: ModeloContrato) -> ModeloSaida:
    return ModeloSaida(
        id=m.id,
        nome=m.nome,
        tipo=m.tipo,
        texto=m.texto,
        descricao=m.descricao,
        parametros=m.parametros or [],
        base_id=m.base_id,
        atualizado_em=m.atualizado_em.isoformat(),
    )


@router.get("/modelos", response_model=list[ModeloSaida])
def listar(db: Db, tipo: TipoModelo | None = None):
    q = sa.select(ModeloContrato).order_by(ModeloContrato.nome)
    if tipo:
        q = q.where(ModeloContrato.tipo == tipo)
    return [_saida(m) for m in db.scalars(q)]


@router.get("/modelos/{id}", response_model=ModeloSaida)
def obter(id: str, db: Db):
    m = db.get(ModeloContrato, id)
    if m is None:
        raise NaoEncontrado("Modelo não encontrado.")
    return _saida(m)


@router.put("/modelos/{id}", response_model=ModeloSaida)
def salvar(id: str, dados: ModeloEntrada, db: Db, response: Response):
    """Grava o modelo (cria, com 201, se o id é novo). Os campos {{...}} do
    texto são conferidos no app, que conhece os campos do sistema."""
    id = validar_id(id)
    if not dados.nome.strip():
        raise RegraNegocio("Informe o nome.")
    if not dados.texto.strip():
        raise RegraNegocio("Informe o texto.")
    chaves = [p.chave for p in dados.parametros]
    for c in chaves:
        if not _CHAVE.match(c):
            raise RegraNegocio(
                f"Chave inválida: {c}. Use minúsculas, números e '_'."
            )
    if len(set(chaves)) != len(chaves):
        raise RegraNegocio("Há parâmetros com a mesma chave.")
    m = db.get(ModeloContrato, id)
    criado = m is None
    if criado:
        m = ModeloContrato(id=id)
        db.add(m)
    elif m.tipo in _ESSENCIAIS and dados.tipo != m.tipo:
        _garantir_outro(db, m)
    for campo, valor in dados.model_dump(exclude={"parametros"}).items():
        setattr(m, campo, valor)
    m.parametros = [p.model_dump(by_alias=True) for p in dados.parametros]
    db.commit()
    if criado:
        response.status_code = status.HTTP_201_CREATED
    return _saida(m)


@router.delete("/modelos/{id}", status_code=status.HTTP_204_NO_CONTENT)
def remover(id: str, db: Db) -> None:
    """Remove o modelo, mantendo ao menos um de locação e um de venda."""
    m = db.get(ModeloContrato, id)
    if m is None:
        return
    if m.tipo in _ESSENCIAIS:
        _garantir_outro(db, m)
    db.delete(m)
    db.commit()


def _garantir_outro(db: Session, m: ModeloContrato) -> None:
    outros = db.scalar(
        sa.select(sa.func.count()).where(
            ModeloContrato.tipo == m.tipo, ModeloContrato.id != m.id
        )
    )
    if not outros:
        raise RegraNegocio(
            f"Mantenha ao menos um modelo de {m.tipo.rotulo.lower()}: "
            "ele é usado na impressão dos contratos."
        )

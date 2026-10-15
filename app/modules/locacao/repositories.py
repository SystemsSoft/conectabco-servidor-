"""Consultas da locação no banco."""

from collections.abc import Sequence
from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.modules.locacao import models as m
from app.modules.locacao.enums import StatusCobranca, StatusContrato


def _paginar(db: Session, q: sa.Select, limite: int, deslocamento: int):
    total = db.scalar(sa.select(sa.func.count()).select_from(q.subquery())) or 0
    return db.scalars(q.limit(limite).offset(deslocamento)).all(), total


class ContratoRepository:
    def __init__(self, db: Session):
        self.db = db

    def obter(self, id: str) -> m.ContratoLocacao | None:
        return self.db.get(m.ContratoLocacao, id)

    def listar(
        self,
        *,
        status: StatusContrato | None = None,
        imovel_id: str | None = None,
        locatario_id: str | None = None,
        busca: str | None = None,
        limite: int = 100,
        deslocamento: int = 0,
    ) -> tuple[Sequence[m.ContratoLocacao], int]:
        q = sa.select(m.ContratoLocacao)
        if status:
            q = q.where(m.ContratoLocacao.status == status)
        if imovel_id:
            q = q.where(m.ContratoLocacao.imovel_id == imovel_id)
        if locatario_id:
            q = q.where(m.ContratoLocacao.locatario_id == locatario_id)
        if busca:
            q = q.where(m.ContratoLocacao.numero.ilike(f"%{busca.strip()}%"))
        q = q.order_by(m.ContratoLocacao.numero)
        return _paginar(self.db, q, limite, deslocamento)


class DespesaRepository:
    def __init__(self, db: Session):
        self.db = db

    def obter(self, id: str) -> m.Despesa | None:
        return self.db.get(m.Despesa, id)

    def listar(
        self, *, contrato_id: str | None = None, limite: int = 100, deslocamento: int = 0
    ) -> tuple[Sequence[m.Despesa], int]:
        q = sa.select(m.Despesa)
        if contrato_id:
            q = q.where(m.Despesa.contrato_id == contrato_id)
        q = q.order_by(m.Despesa.competencia_inicio.desc(), m.Despesa.descricao)
        return _paginar(self.db, q, limite, deslocamento)


class CobrancaRepository:
    def __init__(self, db: Session):
        self.db = db

    def obter(self, id: str) -> m.Cobranca | None:
        return self.db.get(m.Cobranca, id)

    def da_competencia(self, contrato_id: str, competencia: date) -> m.Cobranca | None:
        return self.db.scalar(
            sa.select(m.Cobranca).where(
                m.Cobranca.contrato_id == contrato_id,
                m.Cobranca.competencia == competencia,
            )
        )

    def listar(
        self,
        *,
        contrato_id: str | None = None,
        competencia: date | None = None,
        status: StatusCobranca | None = None,
        limite: int = 100,
        deslocamento: int = 0,
    ) -> tuple[Sequence[m.Cobranca], int]:
        q = sa.select(m.Cobranca)
        if contrato_id:
            q = q.where(m.Cobranca.contrato_id == contrato_id)
        if competencia:
            q = q.where(m.Cobranca.competencia == competencia)
        if status:
            q = q.where(m.Cobranca.status == status)
        q = q.order_by(m.Cobranca.competencia.desc(), m.Cobranca.vencimento)
        return _paginar(self.db, q, limite, deslocamento)


class RepasseRepository:
    def __init__(self, db: Session):
        self.db = db

    def obter(self, cobranca_id: str, contato_id: str) -> m.RepasseRealizado | None:
        return self.db.get(m.RepasseRealizado, (cobranca_id, contato_id))

    def listar(self, cobranca_id: str | None = None) -> Sequence[m.RepasseRealizado]:
        q = sa.select(m.RepasseRealizado)
        if cobranca_id:
            q = q.where(m.RepasseRealizado.cobranca_id == cobranca_id)
        return self.db.scalars(q.order_by(m.RepasseRealizado.data)).all()

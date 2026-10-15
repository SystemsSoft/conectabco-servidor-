"""Numeração sequencial segura entre requisições simultâneas
(ex.: código de imóvel IM-0001, número de contrato)."""

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.database import Base


class Sequencia(Base):
    __tablename__ = "sequencias"

    nome: Mapped[str] = mapped_column(sa.String(50), primary_key=True)
    valor: Mapped[int] = mapped_column(sa.Integer, default=0)


def proximo_valor(db: Session, nome: str) -> int:
    """Incrementa e devolve o contador; trava a linha até o commit."""
    seq = db.execute(
        sa.select(Sequencia).where(Sequencia.nome == nome).with_for_update()
    ).scalar_one_or_none()
    if seq is None:
        seq = Sequencia(nome=nome, valor=0)
        db.add(seq)
    seq.valor += 1
    db.flush()
    return seq.valor

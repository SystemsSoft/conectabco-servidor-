import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DeclaranteDimob(Base):
    """Quem entrega a DIMOB (registro único, id = 1)."""

    __tablename__ = "declarante_dimob"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    documento: Mapped[str] = mapped_column(sa.String(18), default="")
    nome: Mapped[str] = mapped_column(sa.String(200))
    responsavel_nome: Mapped[str] = mapped_column(sa.String(200), default="")
    responsavel_cpf: Mapped[str] = mapped_column(sa.String(14), default="")
    retificadora: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    # Recibo da declaração original, quando retificadora.
    numero_recibo: Mapped[str] = mapped_column(sa.String(30), default="")

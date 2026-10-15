from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.enums import coluna_enum
from app.modules.crm.models import _Auditoria, _Dinheiro, _uuid
from app.modules.temporada.enums import OrigemReserva, SituacaoReserva


class Reserva(_Auditoria, Base):
    """Reserva de hospedagem (ou bloqueio) no período [check_in, check_out):
    a noite do dia de saída fica livre para o próximo hóspede."""

    __tablename__ = "reservas_temporada"
    __table_args__ = (sa.Index("ix_reservas_periodo", "imovel_id", "check_in", "check_out"),)

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    numero: Mapped[str] = mapped_column(sa.String(20), unique=True)
    imovel_id: Mapped[str] = mapped_column(
        sa.ForeignKey("imoveis.id", ondelete="RESTRICT"), index=True
    )
    hospede_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("contatos.id", ondelete="RESTRICT"), index=True
    )
    bloqueio: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    motivo_bloqueio: Mapped[str] = mapped_column(sa.String(200), default="")
    check_in: Mapped[date] = mapped_column(sa.Date)
    check_out: Mapped[date] = mapped_column(sa.Date)
    hospedes: Mapped[int] = mapped_column(sa.Integer, default=1)
    valor_diaria: Mapped[float] = mapped_column(_Dinheiro, default=0)
    taxa_limpeza: Mapped[float] = mapped_column(_Dinheiro, default=0)
    desconto: Mapped[float] = mapped_column(_Dinheiro, default=0)
    valor_pago: Mapped[float] = mapped_column(_Dinheiro, default=0)
    situacao: Mapped[SituacaoReserva] = mapped_column(
        coluna_enum(SituacaoReserva), default=SituacaoReserva.confirmada, index=True
    )
    origem: Mapped[OrigemReserva] = mapped_column(
        coluna_enum(OrigemReserva), default=OrigemReserva.direto
    )
    observacoes: Mapped[str] = mapped_column(sa.Text, default="")

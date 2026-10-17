from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.enums import coluna_enum
from app.modules.crm.models import _Auditoria, _Dinheiro, _uuid
from app.modules.manutencao.enums import (
    ContextoManutencao,
    OrigemManutencao,
    StatusManutencao,
    TipoManutencao,
)


class Manutencao(_Auditoria, Base):
    """Item da pauta de manutenção de um imóvel."""

    __tablename__ = "manutencoes"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    contexto: Mapped[ContextoManutencao] = mapped_column(
        coluna_enum(ContextoManutencao), index=True
    )
    imovel_id: Mapped[str] = mapped_column(
        sa.ForeignKey("imoveis.id", ondelete="RESTRICT"), index=True
    )
    tipo: Mapped[TipoManutencao] = mapped_column(coluna_enum(TipoManutencao))
    tipo_outro: Mapped[str] = mapped_column(sa.String(100), default="")
    descricao: Mapped[str] = mapped_column(sa.Text)
    status: Mapped[StatusManutencao] = mapped_column(
        coluna_enum(StatusManutencao), default=StatusManutencao.pendente, index=True
    )
    data_prevista: Mapped[date | None] = mapped_column(sa.Date)
    # Chamados abertos pelo inquilino no portal ficam ligados ao contrato.
    contrato_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("contratos_locacao.id", ondelete="SET NULL"), index=True
    )
    origem: Mapped[OrigemManutencao] = mapped_column(
        coluna_enum(OrigemManutencao), default=OrigemManutencao.equipe
    )

    diario: Mapped[list["RegistroDiario"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="RegistroDiario.data"
    )


class RegistroDiario(Base):
    """Lançamento do diário: quem fez, o quê e quanto custou."""

    __tablename__ = "manutencao_diario"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    manutencao_id: Mapped[str] = mapped_column(
        sa.ForeignKey("manutencoes.id", ondelete="CASCADE"), index=True
    )
    data: Mapped[date] = mapped_column(sa.Date)
    profissional: Mapped[str] = mapped_column(sa.String(150))
    servico: Mapped[str] = mapped_column(sa.Text)
    material: Mapped[str] = mapped_column(sa.String(500), default="")
    valor_material: Mapped[float] = mapped_column(_Dinheiro, default=0)
    valor_mao_de_obra: Mapped[float] = mapped_column(_Dinheiro, default=0)
    valor_taxa: Mapped[float] = mapped_column(_Dinheiro, default=0)

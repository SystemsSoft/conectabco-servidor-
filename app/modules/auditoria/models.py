from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.enums import coluna_enum
from app.core.tempo import agora
from app.modules.auditoria.enums import (
    EstadoItem,
    StatusAuditoria,
    StatusTranscricao,
    TipoAuditoria,
    TipoMidia,
)
from app.modules.crm.models import _Auditoria


class Auditoria(_Auditoria, Base):
    """Auditoria de um imóvel administrado: checklist em campo, fotos,
    vídeos (com transcrição) e conclusão. Concluída, fica bloqueada e pode
    ser publicada na Área do proprietário."""

    __tablename__ = "auditorias"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    numero: Mapped[str] = mapped_column(sa.String(20), unique=True)
    imovel_id: Mapped[str] = mapped_column(
        sa.ForeignKey("imoveis.id", ondelete="RESTRICT"), index=True
    )
    contrato_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("contratos_locacao.id", ondelete="SET NULL"), index=True
    )
    proprietario_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("contatos.id", ondelete="SET NULL"), index=True
    )
    corretor_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("usuarios.id", ondelete="SET NULL"), index=True
    )
    tipo: Mapped[TipoAuditoria] = mapped_column(coluna_enum(TipoAuditoria))
    status: Mapped[StatusAuditoria] = mapped_column(
        coluna_enum(StatusAuditoria), default=StatusAuditoria.agendada, index=True
    )
    data_agendada: Mapped[date | None] = mapped_column(sa.Date)
    data_realizada: Mapped[date | None] = mapped_column(sa.Date)
    # Estado de conservação, de 1 (ruim) a 5 (ótimo).
    nota: Mapped[int | None] = mapped_column(sa.Integer)
    resumo: Mapped[str] = mapped_column(sa.Text, default="")
    recomendacoes: Mapped[str] = mapped_column(sa.Text, default="")
    publicada: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    concluida_em: Mapped[datetime | None] = mapped_column(sa.DateTime)
    concluida_por_id: Mapped[str | None] = mapped_column(sa.String(36))

    itens: Mapped[list["ItemAuditoria"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="ItemAuditoria.ordem"
    )
    midias: Mapped[list["MidiaAuditoria"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="MidiaAuditoria.criado_em"
    )


class ItemAuditoria(Base):
    __tablename__ = "auditoria_itens"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    auditoria_id: Mapped[str] = mapped_column(
        sa.ForeignKey("auditorias.id", ondelete="CASCADE"), index=True
    )
    ordem: Mapped[int] = mapped_column(sa.Integer, default=0)
    area: Mapped[str] = mapped_column(sa.String(100))
    item: Mapped[str] = mapped_column(sa.String(200))
    estado: Mapped[EstadoItem] = mapped_column(
        coluna_enum(EstadoItem), default=EstadoItem.pendente
    )
    observacao: Mapped[str] = mapped_column(sa.Text, default="")
    manutencao_id: Mapped[str | None] = mapped_column(sa.String(36))


class MidiaAuditoria(Base):
    """Foto ou vídeo da auditoria. Vídeos podem ser transcritos no servidor
    (fila processada em segundo plano) e o texto entra no relatório."""

    __tablename__ = "auditoria_midias"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    auditoria_id: Mapped[str] = mapped_column(
        sa.ForeignKey("auditorias.id", ondelete="CASCADE"), index=True
    )
    item_id: Mapped[str | None] = mapped_column(sa.String(36))
    arquivo_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    tipo: Mapped[TipoMidia] = mapped_column(coluna_enum(TipoMidia))
    titulo: Mapped[str] = mapped_column(sa.String(200), default="")
    transcricao_status: Mapped[StatusTranscricao] = mapped_column(
        coluna_enum(StatusTranscricao), default=StatusTranscricao.naoSolicitada, index=True
    )
    transcricao_texto: Mapped[str] = mapped_column(sa.Text, default="")
    transcricao_erro: Mapped[str] = mapped_column(sa.String(500), default="")
    transcricao_em: Mapped[datetime | None] = mapped_column(sa.DateTime)
    criado_em: Mapped[datetime] = mapped_column(sa.DateTime, default=agora)


class ModeloChecklist(Base):
    """Checklist pronto para novas auditorias (itens por área/cômodo)."""

    __tablename__ = "auditoria_modelos"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    nome: Mapped[str] = mapped_column(sa.String(150))
    itens: Mapped[list] = mapped_column(sa.JSON)  # [{"area": .., "item": ..}]
    padrao: Mapped[bool] = mapped_column(sa.Boolean, default=False)


class ConfiguracaoAuditoria(Base):
    """Registro único (id = 1): prazos das pendências automáticas."""

    __tablename__ = "configuracao_auditoria"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    dados: Mapped[dict] = mapped_column(sa.JSON)

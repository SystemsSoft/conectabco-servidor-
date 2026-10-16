from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.enums import coluna_enum
from app.core.tempo import agora
from app.modules.site.enums import StatusLead, TipoLead


class ConfiguracaoSite(Base):
    """Registro único (id = 1): textos, contatos e funcionalidades do site."""

    __tablename__ = "configuracao_site"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    dados: Mapped[dict] = mapped_column(sa.JSON)
    atualizado_em: Mapped[datetime] = mapped_column(
        sa.DateTime, default=agora, onupdate=agora
    )


class LeadSite(Base):
    """Pedido de contato enviado pelo site. Vira (ou atualiza) um contato no
    CRM, uma tarefa na Central de Relacionamento e, se configurado, um
    atendimento para o próximo corretor da fila."""

    __tablename__ = "leads_site"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    tipo: Mapped[TipoLead] = mapped_column(coluna_enum(TipoLead))
    status: Mapped[StatusLead] = mapped_column(
        coluna_enum(StatusLead), default=StatusLead.novo, index=True
    )
    nome: Mapped[str] = mapped_column(sa.String(200))
    email: Mapped[str] = mapped_column(sa.String(200), default="")
    telefone: Mapped[str] = mapped_column(sa.String(30), default="")
    mensagem: Mapped[str] = mapped_column(sa.Text, default="")
    data_visita: Mapped[datetime | None] = mapped_column(sa.DateTime)
    imovel_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("imoveis.id", ondelete="SET NULL"), index=True
    )
    contato_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("contatos.id", ondelete="SET NULL"), index=True
    )
    corretor_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("usuarios.id", ondelete="SET NULL"), index=True
    )
    atendimento_id: Mapped[str | None] = mapped_column(sa.String(36))
    evento_id: Mapped[str | None] = mapped_column(sa.String(36))
    pagina: Mapped[str] = mapped_column(sa.String(300), default="")
    observacao: Mapped[str] = mapped_column(sa.Text, default="")
    criado_em: Mapped[datetime] = mapped_column(sa.DateTime, default=agora, index=True)
    atualizado_em: Mapped[datetime] = mapped_column(
        sa.DateTime, default=agora, onupdate=agora
    )

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.tempo import agora


class AcessoProprietario(Base):
    """Login do proprietário na Área do proprietário (CPF/CNPJ + senha),
    liberado pela equipe. Mesmas regras do acesso do inquilino."""

    __tablename__ = "acessos_proprietario"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    contato_id: Mapped[str] = mapped_column(
        sa.ForeignKey("contatos.id", ondelete="CASCADE"), unique=True
    )
    login: Mapped[str] = mapped_column(sa.String(14), unique=True)
    senha_hash: Mapped[str] = mapped_column(sa.String(200))
    ativo: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    trocar_senha: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    versao: Mapped[int] = mapped_column(sa.Integer, default=1)
    tentativas: Mapped[int] = mapped_column(sa.Integer, default=0)
    bloqueado_ate: Mapped[datetime | None] = mapped_column(sa.DateTime)
    ultimo_acesso: Mapped[datetime | None] = mapped_column(sa.DateTime)
    criado_em: Mapped[datetime] = mapped_column(sa.DateTime, default=agora)

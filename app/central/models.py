from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import BaseCentral


class Imobiliaria(BaseCentral):
    __tablename__ = "imobiliarias"

    # Identificador curto: cabeçalho X-Imobiliaria, ?imob= e pasta dos arquivos.
    slug: Mapped[str] = mapped_column(sa.String(40), primary_key=True)
    nome: Mapped[str] = mapped_column(sa.String(200))
    # Banco (schema) da imobiliária no servidor MySQL.
    banco: Mapped[str] = mapped_column(sa.String(64), unique=True)
    # Endereço público do site: sitemap, links do QR code e cookie seguro.
    site_url: Mapped[str] = mapped_column(sa.String(200), default="")
    ativa: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    criada_em: Mapped[datetime] = mapped_column(sa.DateTime)
    dominios: Mapped[list["Dominio"]] = relationship(
        back_populates="imobiliaria",
        cascade="all, delete-orphan",
        order_by="Dominio.dominio",
        lazy="selectin",
    )


class Dominio(BaseCentral):
    """Endereço (site e portais) que abre a imobiliária."""

    __tablename__ = "dominios"

    dominio: Mapped[str] = mapped_column(sa.String(253), primary_key=True)
    imobiliaria_slug: Mapped[str] = mapped_column(
        sa.ForeignKey("imobiliarias.slug", ondelete="CASCADE"), index=True
    )
    imobiliaria: Mapped[Imobiliaria] = relationship(back_populates="dominios")

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import BaseCentral
from app.core.ulid import novo_ulid


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
    # Paleta do site e do app (#rrggbb; vazia = a padrão, azul-marinho e dourado).
    cor_primaria: Mapped[str] = mapped_column(sa.String(7), default="")
    cor_destaque: Mapped[str] = mapped_column(sa.String(7), default="")
    criada_em: Mapped[datetime] = mapped_column(sa.DateTime)
    # ULID fixo e único: prefixo dos arquivos dela (imobiliarias/<chave>/...).
    chave: Mapped[str] = mapped_column(sa.String(26), unique=True, default=novo_ulid)
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


class Administrador(BaseCentral):
    """Quem entra no painel da plataforma (/plataforma) e cadastra as
    imobiliárias. Não é usuário de nenhuma imobiliária."""

    __tablename__ = "administradores"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    nome: Mapped[str] = mapped_column(sa.String(150))
    login: Mapped[str] = mapped_column(sa.String(60), unique=True)
    senha_hash: Mapped[str] = mapped_column(sa.String(200))
    ativo: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    # Muda a cada troca de senha: derruba as sessões abertas.
    versao: Mapped[int] = mapped_column(sa.Integer, default=1)
    tentativas: Mapped[int] = mapped_column(sa.Integer, default=0)
    bloqueado_ate: Mapped[datetime | None] = mapped_column(sa.DateTime)
    criado_em: Mapped[datetime] = mapped_column(sa.DateTime)
    ultimo_acesso: Mapped[datetime | None] = mapped_column(sa.DateTime)

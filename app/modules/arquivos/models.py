from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Arquivo(Base):
    """Foto, vídeo ou documento enviado do computador. O conteúdo fica no
    armazenamento (S3) sob `chave`; os cadastros guardam a referência
    `arquivo:<id>`."""

    __tablename__ = "arquivos"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    nome: Mapped[str] = mapped_column(sa.String(255))
    categoria: Mapped[str] = mapped_column(sa.String(20))
    tipo_mime: Mapped[str] = mapped_column(sa.String(120))
    tamanho: Mapped[int] = mapped_column(sa.BigInteger)
    enviado_por_id: Mapped[str | None] = mapped_column(sa.String(36))
    criado_em: Mapped[datetime] = mapped_column(sa.DateTime)
    # imobiliarias/<ULID da imobiliária>/<categoria>/<ULID>; vazia nos de antes
    # do S3 (ainda na pasta antiga, até o gerenciar.py migrar-arquivos).
    chave: Mapped[str | None] = mapped_column(sa.String(120), unique=True)

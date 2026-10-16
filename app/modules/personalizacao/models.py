from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

# Imagens de até alguns MB (o BLOB comum do MySQL vai só até 64 KB).
_Imagem = sa.LargeBinary().with_variant(mysql.MEDIUMBLOB(), "mysql")


class DadosEmpresa(Base):
    """Registro único (id = 1)."""

    __tablename__ = "dados_empresa"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    nome: Mapped[str] = mapped_column(sa.String(200))
    atividade: Mapped[str] = mapped_column(sa.String(100), default="")
    creci: Mapped[str] = mapped_column(sa.String(40), default="")
    documento: Mapped[str] = mapped_column(sa.String(18), default="")
    endereco: Mapped[str] = mapped_column(sa.String(300), default="")
    telefone: Mapped[str] = mapped_column(sa.String(40), default="")
    email: Mapped[str] = mapped_column(sa.String(200), default="")
    site: Mapped[str] = mapped_column(sa.String(200), default="")
    chave_pix: Mapped[str] = mapped_column(sa.String(150), default="")
    logo: Mapped[bytes | None] = mapped_column(_Imagem)
    logo_tipo: Mapped[str] = mapped_column(sa.String(30), default="")
    logo_atualizado_em: Mapped[datetime | None] = mapped_column(sa.DateTime)

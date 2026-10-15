import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.enums import EnumRotulado, coluna_enum
from app.modules.crm.models import _Auditoria, _uuid


class TipoModelo(EnumRotulado):
    locacao = "locacao", "Locação"
    temporada = "temporada", "Temporada"
    venda = "venda", "Compra e venda"
    administracao = "administracao", "Administração"
    autorizacao = "autorizacao", "Autorização de venda"
    outros = "outros", "Outros documentos"


# Textos de contrato podem passar de 64 KB (limite do TEXT no MySQL).
_TextoLongo = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


class ModeloContrato(_Auditoria, Base):
    """Modelo com campos no formato {{campo}} e parâmetros próprios."""

    __tablename__ = "modelos_contrato"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    nome: Mapped[str] = mapped_column(sa.String(150))
    tipo: Mapped[TipoModelo] = mapped_column(coluna_enum(TipoModelo), index=True)
    texto: Mapped[str] = mapped_column(_TextoLongo)
    descricao: Mapped[str] = mapped_column(sa.Text, default="")
    # [{chave, rotulo, tipo, valorPadrao, descricao}]
    parametros: Mapped[list[dict]] = mapped_column(sa.JSON, default=list)
    # Modelo pronto de origem (permite restaurar o texto original).
    base_id: Mapped[str | None] = mapped_column(sa.String(100))

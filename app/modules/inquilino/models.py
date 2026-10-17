from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.enums import coluna_enum
from app.core.tempo import agora
from app.modules.inquilino.enums import OrigemArquivo, TipoArquivoContrato


class AcessoInquilino(Base):
    """Login do locatário no portal (CPF/CNPJ + senha), liberado pela equipe."""

    __tablename__ = "acessos_inquilino"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    contato_id: Mapped[str] = mapped_column(
        sa.ForeignKey("contatos.id", ondelete="CASCADE"), unique=True
    )
    login: Mapped[str] = mapped_column(sa.String(14), unique=True)
    senha_hash: Mapped[str] = mapped_column(sa.String(200))
    ativo: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    # Senha provisória (gerada pela equipe): troca obrigatória no 1º acesso.
    trocar_senha: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    # Muda a cada senha nova ou bloqueio: derruba as sessões abertas.
    versao: Mapped[int] = mapped_column(sa.Integer, default=1)
    tentativas: Mapped[int] = mapped_column(sa.Integer, default=0)
    bloqueado_ate: Mapped[datetime | None] = mapped_column(sa.DateTime)
    ultimo_acesso: Mapped[datetime | None] = mapped_column(sa.DateTime)
    criado_em: Mapped[datetime] = mapped_column(sa.DateTime, default=agora)


class ArquivoContrato(Base):
    """Documento ou mídia ligado a um contrato: contrato assinado, laudo de
    vistoria e outros (da imobiliária); fotos e vídeos do estado do imóvel e
    anexos de chamados (do inquilino)."""

    __tablename__ = "arquivos_contrato"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    contrato_id: Mapped[str] = mapped_column(
        sa.ForeignKey("contratos_locacao.id", ondelete="CASCADE"), index=True
    )
    manutencao_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("manutencoes.id", ondelete="CASCADE"), index=True
    )
    tipo: Mapped[TipoArquivoContrato] = mapped_column(coluna_enum(TipoArquivoContrato))
    origem: Mapped[OrigemArquivo] = mapped_column(coluna_enum(OrigemArquivo))
    titulo: Mapped[str] = mapped_column(sa.String(200))
    observacao: Mapped[str] = mapped_column(sa.Text, default="")
    arquivo_id: Mapped[str] = mapped_column(sa.String(36), index=True)
    visivel_inquilino: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    criado_em: Mapped[datetime] = mapped_column(sa.DateTime, default=agora, index=True)


class Comunicado(Base):
    """Aviso da imobiliária: para um contrato ou, sem contrato, para todos
    os inquilinos com acesso."""

    __tablename__ = "comunicados_inquilino"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    contrato_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("contratos_locacao.id", ondelete="CASCADE"), index=True
    )
    titulo: Mapped[str] = mapped_column(sa.String(200))
    mensagem: Mapped[str] = mapped_column(sa.Text)
    automatico: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    enviado_por_id: Mapped[str | None] = mapped_column(sa.String(36))
    criado_em: Mapped[datetime] = mapped_column(sa.DateTime, default=agora, index=True)


class LeituraComunicado(Base):
    __tablename__ = "leituras_comunicado"

    comunicado_id: Mapped[str] = mapped_column(
        sa.ForeignKey("comunicados_inquilino.id", ondelete="CASCADE"), primary_key=True
    )
    acesso_id: Mapped[str] = mapped_column(
        sa.ForeignKey("acessos_inquilino.id", ondelete="CASCADE"), primary_key=True
    )
    lido_em: Mapped[datetime] = mapped_column(sa.DateTime, default=agora)

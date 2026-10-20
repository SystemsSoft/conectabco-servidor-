"""Integração Sicoob: configuração, registro das chamadas e o que foi
emitido pelas APIs (boletos e cobranças Pix)."""

from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.tempo import agora
from app.modules.crm.models import _Dinheiro, _uuid


class ConfiguracaoSicoob(Base):
    """Linha única (id=1). O token fica fora de `dados` e nunca volta à API."""

    __tablename__ = "configuracao_sicoob"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    dados: Mapped[dict] = mapped_column(sa.JSON, default=dict)
    token_sandbox: Mapped[str] = mapped_column(sa.Text, default="")
    atualizado_em: Mapped[datetime] = mapped_column(sa.DateTime, default=agora, onupdate=agora)


class ChamadaSicoob(Base):
    """Cada requisição feita ao Sicoob (sem token), para conferir os testes."""

    __tablename__ = "sicoob_chamadas"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    criado_em: Mapped[datetime] = mapped_column(sa.DateTime, default=agora, index=True)
    usuario_id: Mapped[str | None] = mapped_column(sa.String(36))
    ambiente: Mapped[str] = mapped_column(sa.String(20))
    api: Mapped[str] = mapped_column(sa.String(20))
    operacao: Mapped[str] = mapped_column(sa.String(100))
    metodo: Mapped[str] = mapped_column(sa.String(10))
    caminho: Mapped[str] = mapped_column(sa.String(500))
    status_http: Mapped[int | None] = mapped_column(sa.Integer)
    duracao_ms: Mapped[int] = mapped_column(sa.Integer, default=0)
    sucesso: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    requisicao: Mapped[str] = mapped_column(sa.Text, default="")
    resposta: Mapped[str] = mapped_column(sa.Text, default="")
    erro: Mapped[str] = mapped_column(sa.String(500), default="")


class BoletoSicoob(Base):
    """Boleto registrado pela API de Cobrança Bancária."""

    __tablename__ = "sicoob_boletos"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    ambiente: Mapped[str] = mapped_column(sa.String(20))
    nosso_numero: Mapped[str] = mapped_column(sa.String(30), index=True)
    seu_numero: Mapped[str] = mapped_column(sa.String(30), default="")
    valor: Mapped[float] = mapped_column(_Dinheiro)
    vencimento: Mapped[date] = mapped_column(sa.Date)
    pagador_nome: Mapped[str] = mapped_column(sa.String(200), default="")
    pagador_documento: Mapped[str] = mapped_column(sa.String(20), default="")
    linha_digitavel: Mapped[str] = mapped_column(sa.String(80), default="")
    codigo_barras: Mapped[str] = mapped_column(sa.String(60), default="")
    situacao: Mapped[str] = mapped_column(sa.String(60), default="Registrado")
    # Cobrança do aluguel que originou o boleto (opcional).
    cobranca_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("cobrancas_locacao.id", ondelete="SET NULL"), index=True
    )
    criado_em: Mapped[datetime] = mapped_column(sa.DateTime, default=agora)
    atualizado_em: Mapped[datetime] = mapped_column(sa.DateTime, default=agora, onupdate=agora)


class PixSicoob(Base):
    """Cobrança Pix imediata (cob) criada pela API Pix Recebimentos."""

    __tablename__ = "sicoob_pix"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    ambiente: Mapped[str] = mapped_column(sa.String(20))
    txid: Mapped[str] = mapped_column(sa.String(40), index=True)
    valor: Mapped[float] = mapped_column(_Dinheiro)
    devedor_nome: Mapped[str] = mapped_column(sa.String(200), default="")
    devedor_documento: Mapped[str] = mapped_column(sa.String(20), default="")
    descricao: Mapped[str] = mapped_column(sa.String(140), default="")
    status: Mapped[str] = mapped_column(sa.String(40), default="ATIVA")
    copia_e_cola: Mapped[str] = mapped_column(sa.Text, default="")
    location: Mapped[str] = mapped_column(sa.String(300), default="")
    cobranca_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("cobrancas_locacao.id", ondelete="SET NULL"), index=True
    )
    criado_em: Mapped[datetime] = mapped_column(sa.DateTime, default=agora)
    atualizado_em: Mapped[datetime] = mapped_column(sa.DateTime, default=agora, onupdate=agora)

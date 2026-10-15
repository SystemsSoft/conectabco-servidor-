"""Tabelas da Administração de Vendas."""

from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.enums import coluna_enum
from app.modules.crm.models import _Auditoria, _Dinheiro, _uuid
from app.modules.vendas.enums import (
    CredorParcelas,
    FormaPagamento,
    PapelParticipacao,
    SistemaAmortizacao,
    StatusParcela,
    StatusVenda,
    TipoParcela,
)

_Percentual = sa.Numeric(7, 4, asdecimal=False)


class Venda(_Auditoria, Base):
    __tablename__ = "vendas"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    numero: Mapped[str] = mapped_column(sa.String(20), unique=True)
    imovel_id: Mapped[str] = mapped_column(
        sa.ForeignKey("imoveis.id", ondelete="RESTRICT"), index=True
    )
    data_venda: Mapped[date] = mapped_column(sa.Date)
    valor_venda: Mapped[float] = mapped_column(_Dinheiro)
    valor_entrada: Mapped[float] = mapped_column(_Dinheiro, default=0)
    vencimento_entrada: Mapped[date | None] = mapped_column(sa.Date)
    forma_pagamento: Mapped[FormaPagamento] = mapped_column(
        coluna_enum(FormaPagamento), default=FormaPagamento.aVista
    )
    # Plano do financiamento próprio (nulo nas demais formas).
    plano_numero_parcelas: Mapped[int | None] = mapped_column(sa.Integer)
    plano_taxa_juros_mes: Mapped[float | None] = mapped_column(_Percentual)
    plano_sistema: Mapped[SistemaAmortizacao | None] = mapped_column(
        coluna_enum(SistemaAmortizacao)
    )
    plano_primeiro_vencimento: Mapped[date | None] = mapped_column(sa.Date)
    credor: Mapped[CredorParcelas] = mapped_column(
        coluna_enum(CredorParcelas), default=CredorParcelas.vendedor
    )
    multa_atraso: Mapped[float] = mapped_column(_Percentual, default=2)
    juros_mes: Mapped[float] = mapped_column(_Percentual, default=1)
    comissao_percentual: Mapped[float] = mapped_column(_Percentual, default=6)
    status: Mapped[StatusVenda] = mapped_column(
        coluna_enum(StatusVenda), default=StatusVenda.ativa, index=True
    )
    clausulas_adicionais: Mapped[str] = mapped_column(sa.Text, default="")
    observacoes: Mapped[str] = mapped_column(sa.Text, default="")

    compradores: Mapped[list["VendaComprador"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="VendaComprador.ordem"
    )
    participacoes: Mapped[list["Participacao"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="Participacao.ordem"
    )


class VendaComprador(Base):
    __tablename__ = "venda_compradores"

    venda_id: Mapped[str] = mapped_column(
        sa.ForeignKey("vendas.id", ondelete="CASCADE"), primary_key=True
    )
    contato_id: Mapped[str] = mapped_column(
        sa.ForeignKey("contatos.id", ondelete="RESTRICT"), primary_key=True
    )
    ordem: Mapped[int] = mapped_column(sa.Integer, default=0)


class Participacao(Base):
    """Vendedor (cota do imóvel) ou corretor (cota da comissão). Corretor
    sem contato representa a própria imobiliária."""

    __tablename__ = "venda_participacoes"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    venda_id: Mapped[str] = mapped_column(
        sa.ForeignKey("vendas.id", ondelete="CASCADE"), index=True
    )
    papel: Mapped[PapelParticipacao] = mapped_column(coluna_enum(PapelParticipacao))
    ordem: Mapped[int] = mapped_column(sa.Integer, default=0)
    contato_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("contatos.id", ondelete="RESTRICT"), index=True
    )
    percentual: Mapped[float] = mapped_column(_Percentual)
    paga_em: Mapped[date | None] = mapped_column(sa.Date)


class Parcela(_Auditoria, Base):
    """Parcela do financiamento próprio (ou a entrada)."""

    __tablename__ = "parcelas_venda"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    venda_id: Mapped[str] = mapped_column(
        sa.ForeignKey("vendas.id", ondelete="CASCADE"), index=True
    )
    numero: Mapped[int] = mapped_column(sa.Integer)
    total_parcelas: Mapped[int] = mapped_column(sa.Integer)
    tipo: Mapped[TipoParcela] = mapped_column(coluna_enum(TipoParcela))
    vencimento: Mapped[date] = mapped_column(sa.Date, index=True)
    valor: Mapped[float] = mapped_column(_Dinheiro)
    amortizacao: Mapped[float] = mapped_column(_Dinheiro, default=0)
    juros: Mapped[float] = mapped_column(_Dinheiro, default=0)
    saldo_devedor: Mapped[float] = mapped_column(_Dinheiro, default=0)
    status: Mapped[StatusParcela] = mapped_column(
        coluna_enum(StatusParcela), default=StatusParcela.aberta, index=True
    )
    data_pagamento: Mapped[date | None] = mapped_column(sa.Date)
    valor_pago: Mapped[float | None] = mapped_column(_Dinheiro)
    multa: Mapped[float] = mapped_column(_Dinheiro, default=0)
    juros_mora: Mapped[float] = mapped_column(_Dinheiro, default=0)
    desconto: Mapped[float] = mapped_column(_Dinheiro, default=0)

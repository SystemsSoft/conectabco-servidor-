"""Tabelas da Administração de Locação."""

from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.enums import coluna_enum
from app.modules.crm.models import _Auditoria, _Dinheiro, _uuid
from app.modules.locacao.enums import (
    FinalidadeLocacao,
    GarantiaLocacao,
    IndiceReajuste,
    NaturezaDespesa,
    ResponsavelDespesa,
    StatusCobranca,
    StatusContrato,
    TipoItemCobranca,
)

_Percentual = sa.Numeric(7, 4, asdecimal=False)


class ContratoLocacao(_Auditoria, Base):
    __tablename__ = "contratos_locacao"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    numero: Mapped[str] = mapped_column(sa.String(20), unique=True)
    # Imóvel e locatário em contrato não podem ser excluídos (RESTRICT).
    imovel_id: Mapped[str] = mapped_column(
        sa.ForeignKey("imoveis.id", ondelete="RESTRICT"), index=True
    )
    locatario_id: Mapped[str] = mapped_column(
        sa.ForeignKey("contatos.id", ondelete="RESTRICT"), index=True
    )
    fiador_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("contatos.id", ondelete="SET NULL")
    )
    finalidade: Mapped[FinalidadeLocacao] = mapped_column(
        coluna_enum(FinalidadeLocacao), default=FinalidadeLocacao.residencial
    )
    garantia: Mapped[GarantiaLocacao] = mapped_column(
        coluna_enum(GarantiaLocacao), default=GarantiaLocacao.fiador
    )
    valor_garantia: Mapped[float | None] = mapped_column(_Dinheiro)
    data_inicio: Mapped[date] = mapped_column(sa.Date)
    prazo_meses: Mapped[int] = mapped_column(sa.Integer, default=30)
    dia_vencimento: Mapped[int] = mapped_column(sa.Integer, default=10)
    valor_aluguel: Mapped[float] = mapped_column(_Dinheiro)
    taxa_administracao: Mapped[float] = mapped_column(_Percentual, default=10)
    taxa_intermediacao: Mapped[float] = mapped_column(_Percentual, default=0)
    indice_reajuste: Mapped[IndiceReajuste] = mapped_column(
        coluna_enum(IndiceReajuste), default=IndiceReajuste.igpm
    )
    multa_atraso: Mapped[float] = mapped_column(_Percentual, default=10)
    juros_mes: Mapped[float] = mapped_column(_Percentual, default=1)
    desconto_pontualidade: Mapped[float] = mapped_column(_Dinheiro, default=0)
    status: Mapped[StatusContrato] = mapped_column(
        coluna_enum(StatusContrato), default=StatusContrato.ativo, index=True
    )
    clausulas_adicionais: Mapped[str] = mapped_column(sa.Text, default="")
    observacoes: Mapped[str] = mapped_column(sa.Text, default="")

    beneficiarios: Mapped[list["Beneficiario"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="Beneficiario.ordem"
    )


class Beneficiario(Base):
    """Proprietário (ou outro beneficiário) que recebe parte do aluguel."""

    __tablename__ = "contrato_beneficiarios"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    contrato_id: Mapped[str] = mapped_column(
        sa.ForeignKey("contratos_locacao.id", ondelete="CASCADE"), index=True
    )
    ordem: Mapped[int] = mapped_column(sa.Integer, default=0)
    contato_id: Mapped[str] = mapped_column(
        sa.ForeignKey("contatos.id", ondelete="RESTRICT"), index=True
    )
    percentual: Mapped[float] = mapped_column(_Percentual)


class Despesa(_Auditoria, Base):
    """Despesa fixa (mensal) ou extraordinária de um contrato."""

    __tablename__ = "despesas_locacao"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    contrato_id: Mapped[str] = mapped_column(
        sa.ForeignKey("contratos_locacao.id", ondelete="CASCADE"), index=True
    )
    descricao: Mapped[str] = mapped_column(sa.String(200))
    valor: Mapped[float] = mapped_column(_Dinheiro)
    natureza: Mapped[NaturezaDespesa] = mapped_column(
        coluna_enum(NaturezaDespesa), default=NaturezaDespesa.fixa
    )
    responsavel: Mapped[ResponsavelDespesa] = mapped_column(
        coluna_enum(ResponsavelDespesa), default=ResponsavelDespesa.locatario
    )
    competencia_inicio: Mapped[date] = mapped_column(sa.Date)
    competencia_fim: Mapped[date | None] = mapped_column(sa.Date)
    dedutivel_ir: Mapped[bool] = mapped_column(sa.Boolean, default=False)


class Cobranca(_Auditoria, Base):
    """Cobrança mensal do locatário (base do boleto e do recibo)."""

    __tablename__ = "cobrancas_locacao"
    __table_args__ = (sa.UniqueConstraint("contrato_id", "competencia"),)

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    contrato_id: Mapped[str] = mapped_column(
        sa.ForeignKey("contratos_locacao.id", ondelete="CASCADE"), index=True
    )
    competencia: Mapped[date] = mapped_column(sa.Date, index=True)
    vencimento: Mapped[date] = mapped_column(sa.Date)
    status: Mapped[StatusCobranca] = mapped_column(
        coluna_enum(StatusCobranca), default=StatusCobranca.aberta, index=True
    )
    data_pagamento: Mapped[date | None] = mapped_column(sa.Date)
    valor_pago: Mapped[float | None] = mapped_column(_Dinheiro)
    multa: Mapped[float] = mapped_column(_Dinheiro, default=0)
    juros: Mapped[float] = mapped_column(_Dinheiro, default=0)
    desconto: Mapped[float] = mapped_column(_Dinheiro, default=0)

    itens: Mapped[list["ItemCobranca"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="ItemCobranca.ordem"
    )


class ItemCobranca(Base):
    __tablename__ = "cobranca_itens"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    cobranca_id: Mapped[str] = mapped_column(
        sa.ForeignKey("cobrancas_locacao.id", ondelete="CASCADE"), index=True
    )
    ordem: Mapped[int] = mapped_column(sa.Integer, default=0)
    descricao: Mapped[str] = mapped_column(sa.String(200))
    valor: Mapped[float] = mapped_column(_Dinheiro)
    tipo: Mapped[TipoItemCobranca] = mapped_column(
        coluna_enum(TipoItemCobranca), default=TipoItemCobranca.outro
    )


class RepasseRealizado(Base):
    """Repasse de uma cobrança paga já feito a um beneficiário."""

    __tablename__ = "repasses_realizados"

    cobranca_id: Mapped[str] = mapped_column(
        sa.ForeignKey("cobrancas_locacao.id", ondelete="CASCADE"), primary_key=True
    )
    contato_id: Mapped[str] = mapped_column(
        sa.ForeignKey("contatos.id", ondelete="CASCADE"), primary_key=True
    )
    data: Mapped[date] = mapped_column(sa.Date)

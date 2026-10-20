"""Tabelas do Financeiro."""

from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.enums import coluna_enum
from app.modules.crm.models import _Auditoria, _Dinheiro, _uuid
from app.modules.financeiro.enums import (
    IndiceMonetario,
    MeioPagamento,
    StatusBoleto,
    StatusLancamento,
    TipoLancamento,
)

_Percentual = sa.Numeric(9, 4, asdecimal=False)


class ContaBancaria(_Auditoria, Base):
    __tablename__ = "contas_bancarias"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    nome: Mapped[str] = mapped_column(sa.String(100))
    banco: Mapped[str] = mapped_column(sa.String(100), default="")
    agencia: Mapped[str] = mapped_column(sa.String(20), default="")
    conta: Mapped[str] = mapped_column(sa.String(30), default="")
    saldo_inicial: Mapped[float] = mapped_column(_Dinheiro, default=0)
    # Dados da cobrança bancária (emissão de boletos).
    convenio: Mapped[str] = mapped_column(sa.String(30), default="")
    carteira: Mapped[str] = mapped_column(sa.String(10), default="")


class Lancamento(_Auditoria, Base):
    """Conta a pagar ou a receber, com a baixa (pagamento/recebimento)."""

    __tablename__ = "lancamentos"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    tipo: Mapped[TipoLancamento] = mapped_column(coluna_enum(TipoLancamento), index=True)
    descricao: Mapped[str] = mapped_column(sa.String(200))
    categoria: Mapped[str] = mapped_column(sa.String(100), default="")
    # Cliente ou fornecedor; o lançamento continua se o contato for excluído.
    contato_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("contatos.id", ondelete="SET NULL"), index=True
    )
    documento: Mapped[str] = mapped_column(sa.String(50), default="")
    observacoes: Mapped[str] = mapped_column(sa.Text, default="")
    valor: Mapped[float] = mapped_column(_Dinheiro)
    vencimento: Mapped[date] = mapped_column(sa.Date, index=True)
    multa_percentual: Mapped[float] = mapped_column(_Percentual, default=0)
    juros_mes_percentual: Mapped[float] = mapped_column(_Percentual, default=0)
    indice: Mapped[IndiceMonetario] = mapped_column(
        coluna_enum(IndiceMonetario), default=IndiceMonetario.nenhum
    )
    status: Mapped[StatusLancamento] = mapped_column(
        coluna_enum(StatusLancamento), default=StatusLancamento.aberto, index=True
    )
    parcela_numero: Mapped[int] = mapped_column(sa.Integer, default=1)
    parcela_total: Mapped[int] = mapped_column(sa.Integer, default=1)
    grupo_id: Mapped[str | None] = mapped_column(sa.String(36), index=True)
    data_baixa: Mapped[date | None] = mapped_column(sa.Date)
    valor_baixa: Mapped[float | None] = mapped_column(_Dinheiro)
    multa: Mapped[float] = mapped_column(_Dinheiro, default=0)
    juros: Mapped[float] = mapped_column(_Dinheiro, default=0)
    correcao: Mapped[float] = mapped_column(_Dinheiro, default=0)
    desconto: Mapped[float] = mapped_column(_Dinheiro, default=0)
    meio: Mapped[MeioPagamento | None] = mapped_column(coluna_enum(MeioPagamento))
    conta_baixa_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("contas_bancarias.id", ondelete="RESTRICT"), index=True
    )


class LinhaExtrato(_Auditoria, Base):
    """Movimento do extrato (valor positivo = crédito, negativo = débito)."""

    __tablename__ = "extrato_bancario"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    conta_id: Mapped[str] = mapped_column(
        sa.ForeignKey("contas_bancarias.id", ondelete="RESTRICT"), index=True
    )
    data: Mapped[date] = mapped_column(sa.Date, index=True)
    descricao: Mapped[str] = mapped_column(sa.String(200))
    valor: Mapped[float] = mapped_column(_Dinheiro)
    documento: Mapped[str] = mapped_column(sa.String(50), default="")
    # Baixa conciliada com esta linha (no máximo uma linha por baixa).
    lancamento_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("lancamentos.id", ondelete="SET NULL"), unique=True
    )


class Boleto(_Auditoria, Base):
    """Boleto emitido para uma conta a receber."""

    __tablename__ = "boletos"
    __table_args__ = (sa.UniqueConstraint("conta_id", "nosso_numero"),)

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    lancamento_id: Mapped[str] = mapped_column(
        sa.ForeignKey("lancamentos.id", ondelete="CASCADE"), index=True
    )
    conta_id: Mapped[str] = mapped_column(
        sa.ForeignKey("contas_bancarias.id", ondelete="RESTRICT"), index=True
    )
    nosso_numero: Mapped[str] = mapped_column(sa.String(20))
    valor: Mapped[float] = mapped_column(_Dinheiro)
    vencimento: Mapped[date] = mapped_column(sa.Date)
    emissao: Mapped[date] = mapped_column(sa.Date)
    status: Mapped[StatusBoleto] = mapped_column(
        coluna_enum(StatusBoleto), default=StatusBoleto.emitido, index=True
    )
    data_pagamento: Mapped[date | None] = mapped_column(sa.Date)
    valor_pago: Mapped[float | None] = mapped_column(_Dinheiro)


class IndiceMensal(Base):
    """Variação mensal de um índice de correção (ex.: IGP-M de 03/2026)."""

    __tablename__ = "indices_mensais"

    indice: Mapped[IndiceMonetario] = mapped_column(
        coluna_enum(IndiceMonetario), primary_key=True
    )
    ano: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    mes: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    percentual: Mapped[float] = mapped_column(_Percentual)


class ConfiguracaoFinanceira(Base):
    """Configuração única (id = 1): valores sugeridos nas contas a receber."""

    __tablename__ = "configuracao_financeira"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    multa_percentual: Mapped[float] = mapped_column(_Percentual, default=2)
    juros_mes_percentual: Mapped[float] = mapped_column(_Percentual, default=1)
    indice_padrao: Mapped[IndiceMonetario] = mapped_column(
        coluna_enum(IndiceMonetario), default=IndiceMonetario.nenhum
    )
    # Link do internet banking, aberto pelo botão "Abrir banco" do Financeiro.
    link_banco: Mapped[str] = mapped_column(sa.String(300), default="")


class PastaDocumento(_Auditoria, Base):
    """Pasta do gerenciador de documentos do Financeiro (boletos baixados do
    banco, relatórios e outros)."""

    __tablename__ = "pastas_documentos"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    nome: Mapped[str] = mapped_column(sa.String(100))


class DocumentoFinanceiro(_Auditoria, Base):
    """Documento guardado numa pasta. O conteúdo fica em `arquivos`; o nome
    é o título exibido, editável sem mexer no arquivo."""

    __tablename__ = "documentos_financeiro"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    pasta_id: Mapped[str] = mapped_column(
        sa.ForeignKey("pastas_documentos.id", ondelete="CASCADE"), index=True
    )
    nome: Mapped[str] = mapped_column(sa.String(255))
    arquivo_id: Mapped[str] = mapped_column(sa.String(36), index=True)

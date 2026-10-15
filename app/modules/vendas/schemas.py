"""Contratos da API das vendas (JSON em camelCase, como no front-end)."""

from datetime import date, datetime
from typing import Annotated

from pydantic import Field

from app.core.schemas import Esquema
from app.modules.vendas.enums import (
    CredorParcelas,
    FormaPagamento,
    SistemaAmortizacao,
    StatusParcela,
    StatusVenda,
    TipoParcela,
)

Valor = Annotated[float, Field(ge=0)]
Percentual = Annotated[float, Field(ge=0, le=100)]


class _Auditoria(Esquema):
    id: str
    criado_em: datetime
    atualizado_em: datetime


class Participacao(Esquema):
    """contatoId nulo na comissão = a própria imobiliária."""

    contato_id: str | None = None
    percentual: Percentual
    paga_em: date | None = None


class PlanoFinanciamento(Esquema):
    numero_parcelas: int
    taxa_juros_mes: Valor
    sistema: SistemaAmortizacao
    primeiro_vencimento: date


class VendaEntrada(Esquema):
    imovel_id: str
    compradores: list[str]
    vendedores: list[Participacao]
    data_venda: date
    valor_venda: Valor
    valor_entrada: Valor = 0
    vencimento_entrada: date | None = None
    forma_pagamento: FormaPagamento = FormaPagamento.aVista
    plano: PlanoFinanciamento | None = None
    credor: CredorParcelas = CredorParcelas.vendedor
    multa_atraso: Percentual = 2
    juros_mes: Percentual = 1
    comissao_percentual: Percentual = 6
    corretores: list[Participacao] = [Participacao(percentual=100)]
    status: StatusVenda = StatusVenda.ativa
    clausulas_adicionais: str = ""
    observacoes: str = ""


class VendaSaida(VendaEntrada, _Auditoria):
    numero: str


class ParcelaEntrada(Esquema):
    venda_id: str
    numero: int
    total_parcelas: int
    tipo: TipoParcela
    vencimento: date
    valor: Valor
    amortizacao: float = 0
    juros: float = 0
    saldo_devedor: float = 0
    status: StatusParcela = StatusParcela.aberta
    data_pagamento: date | None = None
    valor_pago: Valor | None = None
    multa: Valor = 0
    juros_mora: Valor = 0
    desconto: Valor = 0


class ParcelaLote(ParcelaEntrada):
    """Parcela com o id (UUID do app), para gravação em lote."""

    id: str


class ParcelaSaida(ParcelaEntrada, _Auditoria):
    pass

from datetime import date, datetime
from typing import Annotated

from pydantic import Field

from app.core.schemas import Esquema
from app.modules.financeiro.enums import (
    IndiceMonetario,
    MeioPagamento,
    StatusBoleto,
    StatusLancamento,
    TipoLancamento,
)

Valor = Annotated[float, Field(ge=0)]


def Texto(n: int):  # noqa: N802 - usado como tipo
    return Annotated[str, Field(max_length=n)]


class _Auditoria(Esquema):
    id: str
    criado_em: datetime
    atualizado_em: datetime


class ContaBancariaEntrada(Esquema):
    nome: Texto(100)
    banco: Texto(100) = ""
    agencia: Texto(20) = ""
    conta: Texto(30) = ""
    saldo_inicial: float = 0
    convenio: Texto(30) = ""
    carteira: Texto(10) = ""


class ContaBancariaSaida(ContaBancariaEntrada, _Auditoria):
    pass


class LancamentoEntrada(Esquema):
    tipo: TipoLancamento
    descricao: Texto(200)
    categoria: Texto(100) = ""
    contato_id: str | None = None
    documento: Texto(50) = ""
    observacoes: str = ""
    valor: Valor
    vencimento: date
    multa_percentual: float = 0
    juros_mes_percentual: float = 0
    indice: IndiceMonetario = IndiceMonetario.nenhum
    status: StatusLancamento = StatusLancamento.aberto
    parcela_numero: int = 1
    parcela_total: int = 1
    grupo_id: str | None = None
    data_baixa: date | None = None
    valor_baixa: Valor | None = None
    multa: Valor = 0
    juros: Valor = 0
    correcao: float = 0
    desconto: Valor = 0
    meio: MeioPagamento | None = None
    conta_baixa_id: str | None = None


class LancamentoLote(LancamentoEntrada):
    id: str


class LancamentoSaida(LancamentoEntrada, _Auditoria):
    pass


class LinhaExtratoEntrada(Esquema):
    conta_id: str
    data: date
    descricao: Texto(200)
    valor: float = Field(description="Positivo = crédito; negativo = débito")
    documento: Texto(50) = ""
    lancamento_id: str | None = None


class LinhaExtratoSaida(LinhaExtratoEntrada, _Auditoria):
    pass


class BoletoEntrada(Esquema):
    lancamento_id: str
    conta_id: str
    nosso_numero: Texto(20) = Field("", description="Vazio = gerar o próximo da conta")
    valor: Valor
    vencimento: date
    emissao: date
    status: StatusBoleto = StatusBoleto.emitido
    data_pagamento: date | None = None
    valor_pago: Valor | None = None


class BoletoSaida(BoletoEntrada, _Auditoria):
    pass


class IndiceMensal(Esquema):
    indice: IndiceMonetario
    ano: int
    mes: int
    percentual: float


class ConfiguracaoFinanceira(Esquema):
    multa_percentual: float = 2
    juros_mes_percentual: float = 1
    indice_padrao: IndiceMonetario = IndiceMonetario.nenhum

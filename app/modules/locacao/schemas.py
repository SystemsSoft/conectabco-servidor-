"""Contratos da API da locação (JSON em camelCase, como no front-end)."""

from datetime import date, datetime
from typing import Annotated

from pydantic import Field

from app.core.schemas import Esquema
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

Valor = Annotated[float, Field(ge=0)]
Percentual = Annotated[float, Field(ge=0, le=100)]


class _Auditoria(Esquema):
    id: str
    criado_em: datetime
    atualizado_em: datetime


class Beneficiario(Esquema):
    contato_id: str
    percentual: Percentual


class ContratoEntrada(Esquema):
    imovel_id: str
    locatario_id: str
    fiador_id: str | None = None
    beneficiarios: list[Beneficiario]
    finalidade: FinalidadeLocacao = FinalidadeLocacao.residencial
    garantia: GarantiaLocacao = GarantiaLocacao.fiador
    valor_garantia: Valor | None = None
    data_inicio: date
    prazo_meses: int = 30
    dia_vencimento: int = 10
    valor_aluguel: Valor
    taxa_administracao: Percentual = 10
    taxa_intermediacao: Percentual = 0
    indice_reajuste: IndiceReajuste = IndiceReajuste.igpm
    multa_atraso: Percentual = 10
    juros_mes: Percentual = 1
    desconto_pontualidade: Valor = 0
    status: StatusContrato = StatusContrato.ativo
    clausulas_adicionais: str = ""
    observacoes: str = ""


class ContratoSaida(ContratoEntrada, _Auditoria):
    numero: str


class DespesaEntrada(Esquema):
    contrato_id: str
    descricao: Annotated[str, Field(max_length=200)]
    valor: Valor
    natureza: NaturezaDespesa = NaturezaDespesa.fixa
    responsavel: ResponsavelDespesa = ResponsavelDespesa.locatario
    competencia_inicio: date
    competencia_fim: date | None = None
    dedutivel_ir: bool = False


class DespesaSaida(DespesaEntrada, _Auditoria):
    pass


class ItemCobranca(Esquema):
    descricao: Annotated[str, Field(max_length=200)]
    valor: float
    tipo: TipoItemCobranca = TipoItemCobranca.outro


class CobrancaEntrada(Esquema):
    contrato_id: str
    competencia: date
    vencimento: date
    itens: list[ItemCobranca]
    status: StatusCobranca = StatusCobranca.aberta
    data_pagamento: date | None = None
    valor_pago: Valor | None = None
    multa: Valor = 0
    juros: Valor = 0
    desconto: Valor = 0


class CobrancaSaida(CobrancaEntrada, _Auditoria):
    pass


class RepasseEntrada(Esquema):
    data: date


class RepasseSaida(Esquema):
    cobranca_id: str
    contato_id: str
    data: date

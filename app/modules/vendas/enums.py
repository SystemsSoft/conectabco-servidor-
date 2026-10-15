"""Enums das vendas — valores iguais aos nomes do front-end."""

from app.core.enums import EnumRotulado


class FormaPagamento(EnumRotulado):
    aVista = "aVista", "À vista"
    financiamentoBancario = "financiamentoBancario", "Financiamento bancário"
    financiamentoProprio = "financiamentoProprio", "Financiamento próprio"


class SistemaAmortizacao(EnumRotulado):
    price = "price", "Tabela Price"
    sac = "sac", "SAC"
    semJuros = "semJuros", "Sem juros"


class StatusVenda(EnumRotulado):
    ativa = "ativa", "Em andamento"
    quitada = "quitada", "Quitada"
    distratada = "distratada", "Distratada"


class StatusParcela(EnumRotulado):
    aberta = "aberta", "Em aberto"
    paga = "paga", "Paga"
    cancelada = "cancelada", "Cancelada"


class TipoParcela(EnumRotulado):
    entrada = "entrada", "Entrada"
    mensal = "mensal", "Parcela"


class CredorParcelas(EnumRotulado):
    vendedor = "vendedor", "Vendedor(es)"
    imobiliaria = "imobiliaria", "Imobiliária"


class PapelParticipacao(EnumRotulado):
    vendedor = "vendedor", "Vendedor"
    corretor = "corretor", "Corretor (comissão)"

"""Enums da locação — valores iguais aos nomes do front-end."""

from app.core.enums import EnumRotulado


class FinalidadeLocacao(EnumRotulado):
    residencial = "residencial", "Residencial"
    comercial = "comercial", "Comercial"


class GarantiaLocacao(EnumRotulado):
    fiador = "fiador", "Fiador"
    caucao = "caucao", "Caução"
    seguroFianca = "seguroFianca", "Seguro-fiança"
    tituloCapitalizacao = "tituloCapitalizacao", "Título de capitalização"
    semGarantia = "semGarantia", "Sem garantia"


class IndiceReajuste(EnumRotulado):
    igpm = "igpm", "IGP-M (FGV)"
    ipca = "ipca", "IPCA (IBGE)"
    inpc = "inpc", "INPC (IBGE)"
    ivar = "ivar", "IVAR (FGV)"


class StatusContrato(EnumRotulado):
    ativo = "ativo", "Ativo"
    encerrado = "encerrado", "Encerrado"
    rescindido = "rescindido", "Rescindido"


class NaturezaDespesa(EnumRotulado):
    fixa = "fixa", "Fixa (mensal)"
    extraordinaria = "extraordinaria", "Extraordinária"


class ResponsavelDespesa(EnumRotulado):
    locatario = "locatario", "Locatário"
    proprietario = "proprietario", "Proprietário"


class TipoItemCobranca(EnumRotulado):
    aluguel = "aluguel", "Aluguel"
    despesa = "despesa", "Despesa"
    outro = "outro", "Outro"


class StatusCobranca(EnumRotulado):
    aberta = "aberta", "Em aberto"
    paga = "paga", "Paga"
    cancelada = "cancelada", "Cancelada"

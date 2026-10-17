from app.core.enums import EnumRotulado


class TipoArquivoContrato(EnumRotulado):
    contrato = "contrato", "Contrato de locação"
    vistoria = "vistoria", "Laudo de vistoria"
    documento = "documento", "Documento"
    estadoImovel = "estadoImovel", "Estado do imóvel (inquilino)"
    chamado = "chamado", "Anexo de chamado"


class OrigemArquivo(EnumRotulado):
    imobiliaria = "imobiliaria", "Imobiliária"
    inquilino = "inquilino", "Inquilino"

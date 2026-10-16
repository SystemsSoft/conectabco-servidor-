from app.core.enums import EnumRotulado


class TipoLead(EnumRotulado):
    interesse = "interesse", "Interesse em imóvel"
    visita = "visita", "Agendar visita"
    contato = "contato", "Fale conosco"
    anunciar = "anunciar", "Anunciar imóvel"


class StatusLead(EnumRotulado):
    novo = "novo", "Novo"
    emAtendimento = "emAtendimento", "Em atendimento"
    convertido = "convertido", "Convertido"
    descartado = "descartado", "Descartado"

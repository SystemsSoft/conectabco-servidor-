from app.core.enums import EnumRotulado


class ContextoManutencao(EnumRotulado):
    locacao = "locacao", "Locação"
    venda = "venda", "Venda"


class TipoManutencao(EnumRotulado):
    eletrica = "eletrica", "Elétrica"
    alvenaria = "alvenaria", "Alvenaria"
    pintura = "pintura", "Pintura"
    acabamento = "acabamento", "Acabamento"
    outros = "outros", "Outros"


class StatusManutencao(EnumRotulado):
    pendente = "pendente", "Pendente"
    emAndamento = "emAndamento", "Em andamento"
    concluida = "concluida", "Concluída"

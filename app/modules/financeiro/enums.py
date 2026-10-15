from app.core.enums import EnumRotulado


class TipoLancamento(EnumRotulado):
    receber = "receber", "A receber"
    pagar = "pagar", "A pagar"


class StatusLancamento(EnumRotulado):
    aberto = "aberto", "Em aberto"
    baixado = "baixado", "Baixado"
    cancelado = "cancelado", "Cancelado"


class MeioPagamento(EnumRotulado):
    pix = "pix", "PIX"
    boleto = "boleto", "Boleto"
    transferencia = "transferencia", "Transferência"
    dinheiro = "dinheiro", "Dinheiro"
    cartao = "cartao", "Cartão"
    cheque = "cheque", "Cheque"


class IndiceMonetario(EnumRotulado):
    nenhum = "nenhum", "Sem atualização"
    igpm = "igpm", "IGP-M"
    ipca = "ipca", "IPCA"
    inpc = "inpc", "INPC"


class StatusBoleto(EnumRotulado):
    emitido = "emitido", "Emitido"
    pago = "pago", "Pago"
    cancelado = "cancelado", "Cancelado"

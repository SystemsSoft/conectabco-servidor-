from app.core.enums import EnumRotulado


class SituacaoReserva(EnumRotulado):
    preReserva = "preReserva", "Pré-reserva"
    confirmada = "confirmada", "Confirmada"
    cancelada = "cancelada", "Cancelada"


class OrigemReserva(EnumRotulado):
    direto = "direto", "Direto"
    airbnb = "airbnb", "Airbnb"
    booking = "booking", "Booking.com"
    indicacao = "indicacao", "Indicação"
    outro = "outro", "Outro"

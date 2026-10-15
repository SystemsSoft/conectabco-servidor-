from datetime import date, datetime
from typing import Annotated

from pydantic import Field

from app.core.schemas import Esquema
from app.modules.temporada.enums import OrigemReserva, SituacaoReserva

Valor = Annotated[float, Field(ge=0)]


class ReservaEntrada(Esquema):
    imovel_id: str
    hospede_id: str | None = None
    bloqueio: bool = False
    motivo_bloqueio: Annotated[str, Field(max_length=200)] = ""
    check_in: date
    check_out: date
    hospedes: int = 1
    valor_diaria: Valor = 0
    taxa_limpeza: Valor = 0
    desconto: Valor = 0
    valor_pago: Valor = 0
    situacao: SituacaoReserva = SituacaoReserva.confirmada
    origem: OrigemReserva = OrigemReserva.direto
    observacoes: str = ""


class ReservaSaida(ReservaEntrada):
    id: str
    numero: str
    noites: int
    total: float
    saldo: float
    criado_em: datetime
    atualizado_em: datetime

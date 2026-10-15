from datetime import date, datetime
from typing import Annotated

from pydantic import Field

from app.core.schemas import Esquema
from app.modules.manutencao.enums import (
    ContextoManutencao,
    StatusManutencao,
    TipoManutencao,
)

Valor = Annotated[float, Field(ge=0)]


class RegistroDiario(Esquema):
    id: str
    data: date
    profissional: Annotated[str, Field(max_length=150)]
    servico: str
    material: Annotated[str, Field(max_length=500)] = ""
    valor_material: Valor = 0
    valor_mao_de_obra: Valor = 0
    valor_taxa: Valor = Field(0, description="Taxa de manutenção (R$)")


class ManutencaoEntrada(Esquema):
    contexto: ContextoManutencao
    imovel_id: str
    tipo: TipoManutencao
    tipo_outro: Annotated[str, Field(max_length=100)] = ""
    descricao: str
    status: StatusManutencao = StatusManutencao.pendente
    data_prevista: date | None = None
    diario: list[RegistroDiario] = []


class ManutencaoSaida(ManutencaoEntrada):
    id: str
    criado_em: datetime
    atualizado_em: datetime

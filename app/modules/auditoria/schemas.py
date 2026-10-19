from datetime import date, datetime
from typing import Annotated

from pydantic import Field

from app.core.schemas import Esquema
from app.modules.auditoria.enums import (
    AreaPendencia,
    EstadoItem,
    Gravidade,
    StatusAuditoria,
    StatusTranscricao,
    TipoAuditoria,
    TipoMidia,
)


def Texto(n: int):  # noqa: N802
    return Annotated[str, Field(max_length=n)]


class ItemEntrada(Esquema):
    id: str
    area: Texto(100)
    item: Texto(200)
    estado: EstadoItem = EstadoItem.pendente
    observacao: Texto(5000) = ""


class ItemSaida(ItemEntrada):
    manutencao_id: str | None = None


class MidiaEntrada(Esquema):
    referencia: str = Field(description="arquivo:<id> devolvido pelo envio")
    tipo: TipoMidia
    titulo: Texto(200) = ""
    item_id: str | None = None


class MidiaSaida(Esquema):
    id: str
    item_id: str | None
    referencia: str
    tipo: TipoMidia
    titulo: str
    transcricao_status: StatusTranscricao
    transcricao_texto: str
    transcricao_erro: str
    transcricao_em: datetime | None
    criado_em: datetime


class AuditoriaEntrada(Esquema):
    imovel_id: str
    contrato_id: str | None = None
    corretor_id: str | None = None
    tipo: TipoAuditoria = TipoAuditoria.periodica
    status: StatusAuditoria = StatusAuditoria.agendada
    data_agendada: date | None = None
    data_realizada: date | None = None
    nota: Annotated[int, Field(ge=1, le=5)] | None = None
    resumo: Texto(10000) = ""
    recomendacoes: Texto(10000) = ""
    itens: list[ItemEntrada] = Field(default=[], max_length=300)


class AuditoriaSaida(Esquema):
    id: str
    numero: str
    imovel_id: str
    contrato_id: str | None
    proprietario_id: str | None
    corretor_id: str | None
    tipo: TipoAuditoria
    status: StatusAuditoria
    data_agendada: date | None
    data_realizada: date | None
    nota: int | None
    resumo: str
    recomendacoes: str
    publicada: bool
    concluida_em: datetime | None
    concluida_por_id: str | None
    itens: list[ItemSaida]
    midias: list[MidiaSaida]
    criado_em: datetime
    atualizado_em: datetime


class Conclusao(Esquema):
    publicar: bool = False


class Publicacao(Esquema):
    publicada: bool


class ConfiguracaoAuditoria(Esquema):
    """Prazos das pendências automáticas."""

    prazo_repasse_dias: Annotated[int, Field(ge=0, le=90)] = 5
    atraso_critico_dias: Annotated[int, Field(ge=1, le=365)] = 30
    chamado_sem_resposta_horas: Annotated[int, Field(ge=1, le=720)] = 48
    manutencao_parada_dias: Annotated[int, Field(ge=1, le=365)] = 30
    meses_sem_auditoria: Annotated[int, Field(ge=1, le=60)] = 12
    aviso_vencimento_contrato_dias: Annotated[int, Field(ge=1, le=365)] = 60


class ItemModelo(Esquema):
    area: Texto(100)
    item: Texto(200)


class ModeloChecklist(Esquema):
    nome: Texto(150)
    itens: list[ItemModelo] = Field(default=[], max_length=300)
    padrao: bool = False


class ModeloChecklistSaida(ModeloChecklist):
    id: str


class Pendencia(Esquema):
    """Achado da auditoria automática (calculado na hora, não gravado)."""

    id: str
    gravidade: Gravidade
    area: AreaPendencia
    titulo: str
    detalhe: str = ""
    contrato_id: str | None = None
    imovel_id: str | None = None
    proprietario_id: str | None = None


class AcessoPortal(Esquema):
    ativo: bool
    trocar_senha: bool
    bloqueado: bool
    ultimo_acesso: datetime | None


class ResumoProprietario(Esquema):
    contato_id: str
    nome: str
    documento: str
    imoveis: int
    contratos_ativos: int
    aluguel_mensal: float
    em_atraso: float
    criticas: int
    atencoes: int
    ultima_auditoria: date | None
    saude: str = Field(description="verde, amarelo ou vermelho")
    acesso: AcessoPortal | None = None

"""Contratos da API do CRM. Os campos seguem as entidades do front-end
(JSON em camelCase; enums pelo nome usado no Dart)."""

from datetime import date, datetime
from typing import Annotated

from pydantic import Field

from app.core.schemas import Esquema
from app.modules.crm.enums import (
    AnexoTipo,
    EtapaFunil,
    Finalidade,
    Mobiliado,
    OrigemContato,
    PapelContato,
    Prioridade,
    StatusImovel,
    TipoEvento,
    TipoImovel,
    TipoPessoa,
)


def Texto(n: int) -> type[str]:  # noqa: N802 - usado como tipo
    return Annotated[str, Field(max_length=n)]


Valor = Annotated[float, Field(ge=0)]
Quantidade = Annotated[int, Field(ge=0)]


class _Endereco(Esquema):
    cep: Texto(9) = ""
    logradouro: Texto(200) = ""
    numero: Texto(20) = ""
    complemento: Texto(100) = ""
    bairro: Texto(100) = ""
    cidade: Texto(100) = ""
    uf: Texto(2) = ""


class _Auditoria(Esquema):
    id: str
    criado_em: datetime
    atualizado_em: datetime


# ----------------------------------------------------------------- Imóveis


class Anexo(Esquema):
    tipo: AnexoTipo
    titulo: Texto(200) = ""
    url: Texto(1000)


class CaracteristicaPersonalizada(Esquema):
    nome: Texto(100)
    valor: Texto(200) = ""


class ImovelEntrada(_Endereco):
    """Dados enviados ao cadastrar/editar. Código e datas são do servidor."""

    titulo: Texto(200)
    finalidades: list[Finalidade] = [Finalidade.venda]
    tipo: TipoImovel = TipoImovel.apartamento
    status: StatusImovel = StatusImovel.disponivel
    proprietario_id: str | None = None

    referencia: Texto(200) = ""
    condominio_nome: Texto(150) = ""
    exibir_endereco_site: bool = True

    valor_venda: Valor | None = None
    valor_locacao: Valor | None = None
    valor_temporada: Valor | None = None
    valor_condominio: Valor | None = None
    valor_iptu: Valor | None = None
    comissao: Valor | None = None
    aceita_financiamento: bool = False
    aceita_permuta: bool = False

    quartos: Quantidade = 0
    suites: Quantidade = 0
    banheiros: Quantidade = 0
    vagas: Quantidade = 0
    andar: int | None = None
    ano_construcao: int | None = None
    area_util: Valor | None = None
    area_total: Valor | None = None
    area_terreno: Valor | None = None
    mobiliado: Mobiliado = Mobiliado.nao

    comodidades: list[Texto(100)] = []
    personalizadas: list[CaracteristicaPersonalizada] = []

    descricao: str = ""
    observacoes_internas: str = ""

    captador: Texto(150) = ""
    data_captacao: date | None = None
    matricula: Texto(50) = ""
    inscricao_municipal: Texto(50) = ""
    local_chaves: Texto(200) = ""
    exclusividade: bool = False

    anexos: list[Anexo] = []


class ImovelSaida(ImovelEntrada, _Auditoria):
    codigo: str


# ---------------------------------------------------------------- Contatos


class PerfilInteresse(Esquema):
    finalidade: Finalidade = Finalidade.venda
    tipos: list[TipoImovel] = []
    cidade: Texto(100) = ""
    bairros: Texto(500) = Field(default="", description="Separados por vírgula")
    valor_min: Valor | None = None
    valor_max: Valor | None = None
    quartos_min: Quantidade = 0
    suites_min: Quantidade = 0
    vagas_min: Quantidade = 0
    area_min: Valor | None = None
    comodidades: list[Texto(100)] = []
    observacoes: str = ""


class ContatoEntrada(_Endereco):
    nome: Texto(200)
    tipo_pessoa: TipoPessoa = TipoPessoa.fisica
    papeis: list[PapelContato] = [PapelContato.lead]
    documento: Texto(20) = ""
    rg: Texto(20) = ""
    data_nascimento: date | None = None
    estado_civil: Texto(30) | None = None
    profissao: Texto(100) = ""
    nacionalidade: Texto(60) = "Brasileira"

    telefone: Texto(20) = ""
    celular: Texto(20) = ""
    email: Texto(200) = ""
    aceita_contato: bool = True

    origem: OrigemContato = OrigemContato.site
    etapa: EtapaFunil = EtapaFunil.novo
    corretor_responsavel: Texto(150) = ""
    renda_mensal: Valor | None = None
    observacoes: str = ""

    banco: Texto(100) = ""
    agencia: Texto(20) = ""
    conta: Texto(30) = ""
    pix: Texto(150) = ""

    perfil: PerfilInteresse | None = None


class ContatoSaida(ContatoEntrada, _Auditoria):
    pass


# ------------------------------------------------- Central de Relacionamento


class EventoEntrada(Esquema):
    titulo: Texto(200)
    tipo: TipoEvento = TipoEvento.lembrete
    descricao: str = ""
    data_hora: datetime | None = None
    prioridade: Prioridade = Prioridade.normal
    contato_id: str | None = None
    imovel_id: str | None = None
    concluido: bool = False


class EventoSaida(EventoEntrada, _Auditoria):
    pass


# --------------------------------------------------------- Cruzamento


class Sugestao(Esquema):
    """Compatibilidade entre o perfil de um contato e um imóvel."""

    contato_id: str
    contato_nome: str
    imovel_id: str
    imovel_codigo: str
    imovel_titulo: str
    score: int = Field(description="Compatibilidade de 0 a 100")
    atende: list[str]
    nao_atende: list[str]


class ResumoCruzamento(Esquema):
    total_sugestoes: int
    contatos_com_perfil: int
    imoveis_disponiveis: int

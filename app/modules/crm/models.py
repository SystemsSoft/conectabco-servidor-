"""Tabelas do CRM: imóveis, contatos (com perfil de interesse) e a agenda
da Central de Relacionamento."""

import uuid
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.core.enums import coluna_enum
from app.core.tempo import agora
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

_Dinheiro = sa.Numeric(14, 2, asdecimal=False)
_Decimal = sa.Numeric(12, 2, asdecimal=False)


def _uuid() -> str:
    return str(uuid.uuid4())


class _Auditoria:
    criado_em: Mapped[datetime] = mapped_column(sa.DateTime, default=agora)
    atualizado_em: Mapped[datetime] = mapped_column(
        sa.DateTime, default=agora, onupdate=agora
    )


class _Endereco:
    cep: Mapped[str] = mapped_column(sa.String(9), default="")
    logradouro: Mapped[str] = mapped_column(sa.String(200), default="")
    numero: Mapped[str] = mapped_column(sa.String(20), default="")
    complemento: Mapped[str] = mapped_column(sa.String(100), default="")
    bairro: Mapped[str] = mapped_column(sa.String(100), default="")
    cidade: Mapped[str] = mapped_column(sa.String(100), default="")
    uf: Mapped[str] = mapped_column(sa.String(2), default="")


# ---------------------------------------------------------------- Contatos


class Contato(_Endereco, _Auditoria, Base):
    __tablename__ = "contatos"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    nome: Mapped[str] = mapped_column(sa.String(200), index=True)
    tipo_pessoa: Mapped[TipoPessoa] = mapped_column(
        coluna_enum(TipoPessoa), default=TipoPessoa.fisica
    )
    documento: Mapped[str] = mapped_column(sa.String(20), default="", index=True)
    rg: Mapped[str] = mapped_column(sa.String(20), default="")
    data_nascimento: Mapped[date | None] = mapped_column(sa.Date)
    estado_civil: Mapped[str | None] = mapped_column(sa.String(30))
    profissao: Mapped[str] = mapped_column(sa.String(100), default="")
    nacionalidade: Mapped[str] = mapped_column(sa.String(60), default="Brasileira")

    telefone: Mapped[str] = mapped_column(sa.String(20), default="")
    celular: Mapped[str] = mapped_column(sa.String(20), default="")
    email: Mapped[str] = mapped_column(sa.String(200), default="")
    aceita_contato: Mapped[bool] = mapped_column(sa.Boolean, default=True)

    origem: Mapped[OrigemContato] = mapped_column(
        coluna_enum(OrigemContato), default=OrigemContato.site
    )
    etapa: Mapped[EtapaFunil] = mapped_column(
        coluna_enum(EtapaFunil), default=EtapaFunil.novo, index=True
    )
    corretor_responsavel: Mapped[str] = mapped_column(sa.String(150), default="")
    renda_mensal: Mapped[float | None] = mapped_column(_Dinheiro)
    observacoes: Mapped[str] = mapped_column(sa.Text, default="")

    banco: Mapped[str] = mapped_column(sa.String(100), default="")
    agencia: Mapped[str] = mapped_column(sa.String(20), default="")
    conta: Mapped[str] = mapped_column(sa.String(30), default="")
    pix: Mapped[str] = mapped_column(sa.String(150), default="")

    papeis: Mapped[list["ContatoPapel"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )
    perfil: Mapped["PerfilInteresse | None"] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )


class ContatoPapel(Base):
    __tablename__ = "contato_papeis"

    contato_id: Mapped[str] = mapped_column(
        sa.ForeignKey("contatos.id", ondelete="CASCADE"), primary_key=True
    )
    papel: Mapped[PapelContato] = mapped_column(
        coluna_enum(PapelContato), primary_key=True
    )


class PerfilInteresse(Base):
    """O que o contato procura; usado no cruzamento com os imóveis."""

    __tablename__ = "perfis_interesse"

    contato_id: Mapped[str] = mapped_column(
        sa.ForeignKey("contatos.id", ondelete="CASCADE"), primary_key=True
    )
    finalidade: Mapped[Finalidade] = mapped_column(
        coluna_enum(Finalidade), default=Finalidade.venda
    )
    tipos: Mapped[list[str]] = mapped_column(sa.JSON, default=list)
    cidade: Mapped[str] = mapped_column(sa.String(100), default="")
    bairros: Mapped[str] = mapped_column(sa.String(500), default="")
    valor_min: Mapped[float | None] = mapped_column(_Dinheiro)
    valor_max: Mapped[float | None] = mapped_column(_Dinheiro)
    quartos_min: Mapped[int] = mapped_column(sa.Integer, default=0)
    suites_min: Mapped[int] = mapped_column(sa.Integer, default=0)
    vagas_min: Mapped[int] = mapped_column(sa.Integer, default=0)
    area_min: Mapped[float | None] = mapped_column(_Decimal)
    comodidades: Mapped[list[str]] = mapped_column(sa.JSON, default=list)
    observacoes: Mapped[str] = mapped_column(sa.Text, default="")


# ----------------------------------------------------------------- Imóveis


class Imovel(_Endereco, _Auditoria, Base):
    __tablename__ = "imoveis"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    codigo: Mapped[str] = mapped_column(sa.String(20), unique=True)
    titulo: Mapped[str] = mapped_column(sa.String(200))
    tipo: Mapped[TipoImovel] = mapped_column(
        coluna_enum(TipoImovel), default=TipoImovel.apartamento, index=True
    )
    status: Mapped[StatusImovel] = mapped_column(
        coluna_enum(StatusImovel), default=StatusImovel.disponivel, index=True
    )
    proprietario_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("contatos.id", ondelete="SET NULL"), index=True
    )

    referencia: Mapped[str] = mapped_column(sa.String(200), default="")
    condominio_nome: Mapped[str] = mapped_column(sa.String(150), default="")
    exibir_endereco_site: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    # Site: só aparecem os publicados e disponíveis; destaques vão na home.
    publicar_site: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    destaque_site: Mapped[bool] = mapped_column(sa.Boolean, default=False)

    valor_venda: Mapped[float | None] = mapped_column(_Dinheiro)
    valor_locacao: Mapped[float | None] = mapped_column(_Dinheiro)
    valor_temporada: Mapped[float | None] = mapped_column(_Dinheiro)
    valor_condominio: Mapped[float | None] = mapped_column(_Dinheiro)
    valor_iptu: Mapped[float | None] = mapped_column(_Dinheiro)
    comissao: Mapped[float | None] = mapped_column(_Decimal)
    aceita_financiamento: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    aceita_permuta: Mapped[bool] = mapped_column(sa.Boolean, default=False)

    quartos: Mapped[int] = mapped_column(sa.Integer, default=0)
    suites: Mapped[int] = mapped_column(sa.Integer, default=0)
    banheiros: Mapped[int] = mapped_column(sa.Integer, default=0)
    vagas: Mapped[int] = mapped_column(sa.Integer, default=0)
    andar: Mapped[int | None] = mapped_column(sa.Integer)
    ano_construcao: Mapped[int | None] = mapped_column(sa.Integer)
    area_util: Mapped[float | None] = mapped_column(_Decimal)
    area_total: Mapped[float | None] = mapped_column(_Decimal)
    area_terreno: Mapped[float | None] = mapped_column(_Decimal)
    mobiliado: Mapped[Mobiliado] = mapped_column(
        coluna_enum(Mobiliado), default=Mobiliado.nao
    )
    comodidades: Mapped[list[str]] = mapped_column(sa.JSON, default=list)

    descricao: Mapped[str] = mapped_column(sa.Text, default="")
    observacoes_internas: Mapped[str] = mapped_column(sa.Text, default="")

    captador: Mapped[str] = mapped_column(sa.String(150), default="")
    data_captacao: Mapped[date | None] = mapped_column(sa.Date)
    matricula: Mapped[str] = mapped_column(sa.String(50), default="")
    inscricao_municipal: Mapped[str] = mapped_column(sa.String(50), default="")
    local_chaves: Mapped[str] = mapped_column(sa.String(200), default="")
    exclusividade: Mapped[bool] = mapped_column(sa.Boolean, default=False)

    finalidades: Mapped[list["ImovelFinalidade"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )
    personalizadas: Mapped[list["CaracteristicaPersonalizada"]] = relationship(
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="CaracteristicaPersonalizada.ordem",
    )
    anexos: Mapped[list["Anexo"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin", order_by="Anexo.ordem"
    )


class ImovelFinalidade(Base):
    __tablename__ = "imovel_finalidades"

    imovel_id: Mapped[str] = mapped_column(
        sa.ForeignKey("imoveis.id", ondelete="CASCADE"), primary_key=True
    )
    finalidade: Mapped[Finalidade] = mapped_column(
        coluna_enum(Finalidade), primary_key=True
    )


class CaracteristicaPersonalizada(Base):
    """Característica criada pelo usuário (ex.: "Pé-direito": "4 m")."""

    __tablename__ = "imovel_caracteristicas"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    imovel_id: Mapped[str] = mapped_column(
        sa.ForeignKey("imoveis.id", ondelete="CASCADE"), index=True
    )
    ordem: Mapped[int] = mapped_column(sa.Integer, default=0)
    nome: Mapped[str] = mapped_column(sa.String(100))
    valor: Mapped[str] = mapped_column(sa.String(200), default="")


class Anexo(Base):
    __tablename__ = "imovel_anexos"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True, autoincrement=True)
    imovel_id: Mapped[str] = mapped_column(
        sa.ForeignKey("imoveis.id", ondelete="CASCADE"), index=True
    )
    ordem: Mapped[int] = mapped_column(sa.Integer, default=0)
    tipo: Mapped[AnexoTipo] = mapped_column(coluna_enum(AnexoTipo))
    titulo: Mapped[str] = mapped_column(sa.String(200), default="")
    url: Mapped[str] = mapped_column(sa.String(1000))


# ------------------------------------------------- Central de Relacionamento


class Evento(_Auditoria, Base):
    """Anotação, lembrete, recado, visita, ligação ou reunião."""

    __tablename__ = "eventos"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    titulo: Mapped[str] = mapped_column(sa.String(200))
    tipo: Mapped[TipoEvento] = mapped_column(
        coluna_enum(TipoEvento), default=TipoEvento.lembrete
    )
    descricao: Mapped[str] = mapped_column(sa.Text, default="")
    data_hora: Mapped[datetime | None] = mapped_column(sa.DateTime, index=True)
    prioridade: Mapped[Prioridade] = mapped_column(
        coluna_enum(Prioridade), default=Prioridade.normal
    )
    contato_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("contatos.id", ondelete="SET NULL"), index=True
    )
    imovel_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("imoveis.id", ondelete="SET NULL"), index=True
    )
    concluido: Mapped[bool] = mapped_column(sa.Boolean, default=False)

"""Tabelas da Equipe e Segurança."""

from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.enums import coluna_enum
from app.core.tempo import agora
from app.modules.crm.models import _Auditoria, _Dinheiro, _uuid
from app.modules.equipe.enums import (
    ModuloSistema,
    OrigemAtendimento,
    PerfilAcesso,
    StatusComissao,
    StatusFila,
    TipoAtividade,
    TipoComissao,
)


class Usuario(_Auditoria, Base):
    """Quem acessa o sistema (distinto dos contatos do CRM)."""

    __tablename__ = "usuarios"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    nome: Mapped[str] = mapped_column(sa.String(150))
    # Nome de usuário para entrar (ex.: "Marcelo"); comparado sem diferenciar
    # maiúsculas de minúsculas.
    login: Mapped[str] = mapped_column(sa.String(60), unique=True)
    # Contato (opcional).
    email: Mapped[str] = mapped_column(sa.String(200), default="")
    senha_hash: Mapped[str] = mapped_column(sa.String(200))
    perfil: Mapped[PerfilAcesso] = mapped_column(coluna_enum(PerfilAcesso))
    # {"modulos": {"cadastrosCrm": ["visualizar", ...]}, "especiais": [...]}
    permissoes: Mapped[dict] = mapped_column(sa.JSON)
    ativo: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    telefone: Mapped[str] = mapped_column(sa.String(20), default="")
    creci: Mapped[str] = mapped_column(sa.String(30), default="")
    atende_na_fila: Mapped[bool] = mapped_column(sa.Boolean, default=False)

    def pode(self, modulo: ModuloSistema | str, acao: str) -> bool:
        acoes = (self.permissoes or {}).get("modulos", {}).get(str(modulo), [])
        return acao in acoes

    def tem_especial(self, especial: str) -> bool:
        return especial in (self.permissoes or {}).get("especiais", [])

    @property
    def administrador(self) -> bool:
        return self.tem_especial("gerenciarUsuarios")


class Sessao(Base):
    """Login ativo; o token aponta para ela (excluir = desconectar)."""

    __tablename__ = "sessoes"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    usuario_id: Mapped[str] = mapped_column(
        sa.ForeignKey("usuarios.id", ondelete="CASCADE"), index=True
    )
    inicio: Mapped[datetime] = mapped_column(sa.DateTime, default=agora)
    ultima_atividade: Mapped[datetime] = mapped_column(sa.DateTime, default=agora)
    dispositivo: Mapped[str] = mapped_column(sa.String(200), default="")


class ConfiguracaoSeguranca(Base):
    __tablename__ = "configuracao_seguranca"

    id: Mapped[int] = mapped_column(sa.Integer, primary_key=True)
    limite_sessoes: Mapped[int] = mapped_column(sa.Integer, default=5)
    inatividade_minutos: Mapped[int] = mapped_column(sa.Integer, default=30)


class Atividade(Base):
    """Histórico de ações (fica mesmo se o usuário for excluído)."""

    __tablename__ = "atividades"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    usuario_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("usuarios.id", ondelete="SET NULL"), index=True
    )
    tipo: Mapped[TipoAtividade] = mapped_column(coluna_enum(TipoAtividade))
    descricao: Mapped[str] = mapped_column(sa.String(300))
    quando: Mapped[datetime] = mapped_column(sa.DateTime, default=agora, index=True)
    modulo: Mapped[ModuloSistema | None] = mapped_column(coluna_enum(ModuloSistema))


class ItemFila(Base):
    """Posição de um corretor na fila de atendimento."""

    __tablename__ = "fila_atendimento"

    usuario_id: Mapped[str] = mapped_column(
        sa.ForeignKey("usuarios.id", ondelete="CASCADE"), primary_key=True
    )
    posicao: Mapped[int] = mapped_column(sa.Integer)
    status: Mapped[StatusFila] = mapped_column(coluna_enum(StatusFila))
    desde: Mapped[datetime] = mapped_column(sa.DateTime)


class Atendimento(Base):
    __tablename__ = "atendimentos"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    corretor_id: Mapped[str] = mapped_column(
        sa.ForeignKey("usuarios.id", ondelete="RESTRICT"), index=True
    )
    cliente_nome: Mapped[str] = mapped_column(sa.String(200))
    origem: Mapped[OrigemAtendimento] = mapped_column(coluna_enum(OrigemAtendimento))
    iniciado_em: Mapped[datetime] = mapped_column(sa.DateTime, index=True)
    contato_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("contatos.id", ondelete="SET NULL")
    )
    observacao: Mapped[str] = mapped_column(sa.Text, default="")
    finalizado_em: Mapped[datetime | None] = mapped_column(sa.DateTime)


class RegraComissao(Base):
    __tablename__ = "regras_comissao"

    usuario_id: Mapped[str] = mapped_column(
        sa.ForeignKey("usuarios.id", ondelete="CASCADE"), primary_key=True
    )
    percentual_venda: Mapped[float] = mapped_column(sa.Numeric(7, 4, asdecimal=False))
    percentual_locacao: Mapped[float] = mapped_column(sa.Numeric(7, 4, asdecimal=False))
    percentual_captacao: Mapped[float] = mapped_column(sa.Numeric(7, 4, asdecimal=False))
    meta_mensal: Mapped[float] = mapped_column(_Dinheiro, default=0)


class LancamentoComissao(_Auditoria, Base):
    __tablename__ = "comissoes_equipe"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    usuario_id: Mapped[str] = mapped_column(
        sa.ForeignKey("usuarios.id", ondelete="RESTRICT"), index=True
    )
    tipo: Mapped[TipoComissao] = mapped_column(coluna_enum(TipoComissao))
    competencia: Mapped[date] = mapped_column(sa.Date, index=True)
    valor: Mapped[float] = mapped_column(_Dinheiro)
    referencia: Mapped[str] = mapped_column(sa.String(60), default="")
    base_valor: Mapped[float] = mapped_column(_Dinheiro, default=0)
    percentual: Mapped[float] = mapped_column(sa.Numeric(7, 4, asdecimal=False), default=0)
    observacao: Mapped[str] = mapped_column(sa.Text, default="")
    status: Mapped[StatusComissao] = mapped_column(
        coluna_enum(StatusComissao), default=StatusComissao.pendente
    )
    data_pagamento: Mapped[date | None] = mapped_column(sa.Date)


class Mensagem(Base):
    """Chat interno: conversa "geral" ou direta "dm:<id1>:<id2>"."""

    __tablename__ = "mensagens"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_uuid)
    conversa_id: Mapped[str] = mapped_column(sa.String(100), index=True)
    remetente_id: Mapped[str] = mapped_column(
        sa.ForeignKey("usuarios.id", ondelete="RESTRICT"), index=True
    )
    texto: Mapped[str] = mapped_column(sa.Text)
    enviada_em: Mapped[datetime] = mapped_column(sa.DateTime, index=True)
    lida_por: Mapped[list[str]] = mapped_column(sa.JSON, default=list)

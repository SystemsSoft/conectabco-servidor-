from datetime import date, datetime
from typing import Annotated

from pydantic import Field

from app.core.schemas import Esquema
from app.modules.equipe.enums import (
    ModuloSistema,
    OrigemAtendimento,
    PerfilAcesso,
    StatusComissao,
    StatusFila,
    TipoAtividade,
    TipoComissao,
)


def Texto(n: int):  # noqa: N802 - usado como tipo
    return Annotated[str, Field(max_length=n)]


class Permissoes(Esquema):
    modulos: dict[str, list[str]] = {}
    especiais: list[str] = []


class UsuarioEntrada(Esquema):
    nome: Texto(150)
    login: Texto(60) = Field(description="Nome de usuário para entrar")
    email: Texto(200) = ""
    perfil: PerfilAcesso
    permissoes: Permissoes
    ativo: bool = True
    telefone: Texto(20) = ""
    creci: Texto(30) = ""
    atende_na_fila: bool = False
    senha: str | None = Field(
        None, description="Obrigatória ao criar; ao editar, só se for trocar"
    )


class UsuarioSaida(Esquema):
    id: str
    nome: str
    login: str
    email: str
    perfil: PerfilAcesso
    permissoes: Permissoes
    ativo: bool
    telefone: str
    creci: str
    atende_na_fila: bool
    criado_em: datetime


class Login(Esquema):
    usuario: str = Field(description="Nome de usuário (login)")
    senha: str


class LoginSaida(Esquema):
    token: str
    sessao_id: str
    usuario: UsuarioSaida


class AlterarSenha(Esquema):
    senha_atual: str
    nova_senha: str


class SessaoSaida(Esquema):
    id: str
    usuario_id: str
    inicio: datetime
    ultima_atividade: datetime
    dispositivo: str


class ConfiguracaoSeguranca(Esquema):
    limite_sessoes: int = 5
    inatividade_minutos: int = 30


class AtividadeEntrada(Esquema):
    tipo: TipoAtividade
    descricao: Texto(300)
    modulo: ModuloSistema | None = None


class AtividadeSaida(AtividadeEntrada):
    id: str
    usuario_id: str | None
    quando: datetime


class ItemFila(Esquema):
    usuario_id: str
    status: StatusFila
    desde: datetime


class Atendimento(Esquema):
    corretor_id: str
    cliente_nome: Texto(200)
    origem: OrigemAtendimento
    iniciado_em: datetime
    contato_id: str | None = None
    observacao: str = ""
    finalizado_em: datetime | None = None


class AtendimentoSaida(Atendimento):
    id: str


class RegraComissao(Esquema):
    percentual_venda: float = 30
    percentual_locacao: float = 50
    percentual_captacao: float = 10
    meta_mensal: float = 0


class RegraComissaoSaida(RegraComissao):
    usuario_id: str


class LancamentoComissao(Esquema):
    usuario_id: str
    tipo: TipoComissao
    competencia: date
    valor: float
    referencia: Texto(60) = ""
    base_valor: float = 0
    percentual: float = 0
    observacao: str = ""
    status: StatusComissao = StatusComissao.pendente
    data_pagamento: date | None = None


class LancamentoComissaoSaida(LancamentoComissao):
    id: str


class MensagemEntrada(Esquema):
    conversa_id: Texto(100)
    remetente_id: str
    texto: str
    enviada_em: datetime
    lida_por: list[str] = []


class MensagemLote(MensagemEntrada):
    id: str


class MensagemSaida(MensagemEntrada):
    id: str

"""Regras da Equipe e Segurança (equivalentes aos casos de uso do app)."""

import re
from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.errors import NaoEncontrado, RegraNegocio, validar_id
from app.core.seguranca import criar_token, hash_senha, verificar_senha
from app.core.tempo import agora
from app.modules.equipe import models as m
from app.modules.equipe import schemas as s
from app.modules.equipe.enums import ModuloSistema, TipoAtividade

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SENHA_MINIMA = 8


def configuracao(db: Session) -> m.ConfiguracaoSeguranca:
    return db.get(m.ConfiguracaoSeguranca, 1) or m.ConfiguracaoSeguranca(
        id=1, limite_sessoes=5, inatividade_minutos=30
    )


def registrar(
    db: Session, usuario_id: str | None, tipo: TipoAtividade, descricao: str,
    modulo: ModuloSistema | None = None,
) -> None:  # fmt: skip
    db.add(m.Atividade(usuario_id=usuario_id, tipo=tipo, descricao=descricao[:300],
                       modulo=modulo, quando=agora()))  # fmt: skip


def usuario_saida(u: m.Usuario) -> s.UsuarioSaida:
    return s.UsuarioSaida.model_validate(u)


def _validar_senha(senha: str) -> None:
    if len(senha) < SENHA_MINIMA:
        raise RegraNegocio(f"A senha precisa de ao menos {SENHA_MINIMA} caracteres.")


# ------------------------------------------------------------------- Login


def sessoes_ativas(db: Session) -> list[m.Sessao]:
    cfg = configuracao(db)
    limite = agora() - timedelta(minutes=cfg.inatividade_minutos)
    # Limpa as expiradas e devolve as que ainda contam como conectadas.
    db.execute(sa.delete(m.Sessao).where(m.Sessao.ultima_atividade < limite))
    return list(db.scalars(sa.select(m.Sessao)))


def entrar(db: Session, dados: s.Login, dispositivo: str) -> s.LoginSaida:
    email = dados.email.strip().lower()
    u = db.scalar(sa.select(m.Usuario).where(sa.func.lower(m.Usuario.email) == email))
    if u is None or not verificar_senha(dados.senha, u.senha_hash):
        raise RegraNegocio("E-mail ou senha incorretos.")
    if not u.ativo:
        raise RegraNegocio("Este usuário está desativado.")
    ativas = sessoes_ativas(db)
    usuarios = {x.usuario_id for x in ativas}
    cfg = configuracao(db)
    if u.id not in usuarios and len(usuarios) >= cfg.limite_sessoes:
        raise RegraNegocio(
            f"Limite de {cfg.limite_sessoes} usuário(s) simultâneo(s) atingido. "
            "Peça a um administrador para encerrar uma sessão."
        )
    sessao = m.Sessao(usuario_id=u.id, dispositivo=dispositivo[:200],
                      inicio=agora(), ultima_atividade=agora())  # fmt: skip
    db.add(sessao)
    registrar(db, u.id, TipoAtividade.login, "Entrou no sistema")
    db.commit()
    return s.LoginSaida(token=criar_token(u.id, sessao.id), sessao_id=sessao.id,
                        usuario=usuario_saida(u))  # fmt: skip


def sair(db: Session, usuario: m.Usuario, sessao_id: str | None) -> None:
    if sessao_id:
        db.execute(sa.delete(m.Sessao).where(m.Sessao.id == sessao_id))
    registrar(db, usuario.id, TipoAtividade.logout, "Saiu do sistema")
    db.commit()


def alterar_senha(db: Session, usuario: m.Usuario, dados: s.AlterarSenha) -> None:
    if not verificar_senha(dados.senha_atual, usuario.senha_hash):
        raise RegraNegocio("A senha atual não confere.")
    _validar_senha(dados.nova_senha)
    usuario.senha_hash = hash_senha(dados.nova_senha)
    registrar(db, usuario.id, TipoAtividade.edicao, "Alterou a própria senha",
              ModuloSistema.equipeSeguranca)  # fmt: skip
    db.commit()


# ---------------------------------------------------------------- Usuários


def _admins_ativos(db: Session, exceto: str) -> int:
    return sum(
        1
        for u in db.scalars(sa.select(m.Usuario).where(m.Usuario.id != exceto))
        if u.ativo and u.administrador
    )


def salvar_usuario(db: Session, id: str, d: s.UsuarioEntrada, autor: m.Usuario):
    id = validar_id(id)
    if not d.nome.strip():
        raise RegraNegocio("Informe o nome.")
    email = d.email.strip().lower()
    if not _EMAIL.match(email):
        raise RegraNegocio("E-mail inválido.")
    outro = db.scalar(
        sa.select(m.Usuario.id).where(
            sa.func.lower(m.Usuario.email) == email, m.Usuario.id != id
        )
    )
    if outro:
        raise RegraNegocio("Já existe um usuário com este e-mail.")
    u = db.get(m.Usuario, id)
    criado = u is None
    if criado:
        if not d.senha:
            raise RegraNegocio("Defina uma senha para o novo usuário.")
        u = m.Usuario(id=id)
        db.add(u)
    else:
        perde_admin = u.administrador and u.ativo and (
            not d.ativo or "gerenciarUsuarios" not in d.permissoes.especiais
        )
        if perde_admin and _admins_ativos(db, id) == 0:
            raise RegraNegocio("Mantenha ao menos um administrador ativo.")
        if u.ativo and not d.ativo:
            db.execute(sa.delete(m.Sessao).where(m.Sessao.usuario_id == id))
    if d.senha:
        _validar_senha(d.senha)
        u.senha_hash = hash_senha(d.senha)
    for campo, valor in d.model_dump(exclude={"senha", "permissoes"}).items():
        setattr(u, campo, valor)
    u.email = email
    u.permissoes = d.permissoes.model_dump()
    registrar(db, autor.id, TipoAtividade.criacao if criado else TipoAtividade.edicao,
              f"{'Criou' if criado else 'Editou'} o usuário {u.nome}",
              ModuloSistema.equipeSeguranca)  # fmt: skip
    db.commit()
    return usuario_saida(u), criado


def remover_usuario(db: Session, id: str, autor: m.Usuario) -> None:
    u = db.get(m.Usuario, id)
    if u is None:
        raise NaoEncontrado("Usuário não encontrado.")
    if u.id == autor.id:
        raise RegraNegocio("Você não pode excluir o usuário que está em uso.")
    if u.administrador and _admins_ativos(db, id) == 0:
        raise RegraNegocio("Mantenha ao menos um administrador ativo.")
    historico = any(
        db.scalar(sa.select(sa.func.count()).where(cond))
        for cond in (
            m.Atendimento.corretor_id == id,
            m.LancamentoComissao.usuario_id == id,
            m.Mensagem.remetente_id == id,
        )
    )
    if historico:
        raise RegraNegocio(
            "O usuário tem atendimentos, comissões ou mensagens. "
            "Desative o acesso em vez de excluir."
        )
    registrar(db, autor.id, TipoAtividade.exclusao, f"Excluiu o usuário {u.nome}",
              ModuloSistema.equipeSeguranca)  # fmt: skip
    db.delete(u)
    db.commit()


def criar_administrador(db: Session, nome: str, email: str, senha: str) -> m.Usuario:
    """Usado pelo gerenciar.py para o primeiro acesso."""
    from app.modules.equipe.enums import PerfilAcesso, permissoes_do_perfil

    _validar_senha(senha)
    email = email.strip().lower()
    if not _EMAIL.match(email):
        raise RegraNegocio("E-mail inválido.")
    u = db.scalar(sa.select(m.Usuario).where(sa.func.lower(m.Usuario.email) == email))
    if u is None:
        u = m.Usuario(email=email, criado_em=agora())
        db.add(u)
    u.nome = nome
    u.perfil = PerfilAcesso.administrador
    u.permissoes = permissoes_do_perfil(PerfilAcesso.administrador)
    u.ativo = True
    u.senha_hash = hash_senha(senha)
    db.commit()
    return u

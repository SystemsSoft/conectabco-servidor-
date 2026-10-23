"""Login do painel da plataforma: administradores do banco central, senha com
bloqueio por tentativas, sessão em cookie assinado com uma chave só da
plataforma (separada da de cada imobiliária) e token CSRF nos formulários."""

import base64
import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.central import models as m
from app.core.errors import RegraNegocio
from app.core.seguranca import _segredo, hash_senha, verificar_senha
from app.core.tempo import agora

COOKIE = "plataforma"
SESSAO_HORAS = 8
TENTATIVAS = 5
BLOQUEIO = timedelta(minutes=15)


def _chave() -> str:
    return hmac.new(_segredo().encode(), b"plataforma", hashlib.sha256).hexdigest()


def _por_login(db: Session, login: str) -> m.Administrador | None:
    return db.scalar(
        sa.select(m.Administrador).where(
            sa.func.lower(m.Administrador.login) == login.strip().lower()
        )
    )


def criar_administrador(db: Session, nome: str, login: str, senha: str) -> m.Administrador:
    """Cria o administrador ou, se o login já existe, redefine a senha dele."""
    from app.modules.equipe.services import _validar_login, _validar_senha, aparar

    login, senha = aparar(login), aparar(senha)
    _validar_login(login)
    _validar_senha(senha)
    if not nome.strip():
        raise RegraNegocio("Informe o nome.")
    a = _por_login(db, login)
    if a is None:
        a = m.Administrador(id=str(uuid.uuid4()), login=login, versao=1, criado_em=agora())
        db.add(a)
    else:
        a.versao += 1  # derruba as sessões com a senha antiga
    a.nome, a.senha_hash, a.ativo = nome.strip(), hash_senha(senha), True
    a.tentativas, a.bloqueado_ate = 0, None
    db.commit()
    return a


def autenticar(db: Session, login: str, senha: str) -> m.Administrador:
    erro = RegraNegocio("Usuário ou senha incorretos.")
    a = _por_login(db, login)
    if a is None:
        verificar_senha(senha, hash_senha("x"))  # mesmo tempo de resposta
        raise erro
    momento = agora()
    if a.bloqueado_ate and a.bloqueado_ate > momento:
        raise RegraNegocio("Muitas tentativas. Tente novamente em alguns minutos.")
    if not verificar_senha(senha, a.senha_hash):
        a.tentativas += 1
        if a.tentativas >= TENTATIVAS:
            a.tentativas, a.bloqueado_ate = 0, momento + BLOQUEIO
        db.commit()
        raise erro
    if not a.ativo:
        raise RegraNegocio("Seu acesso ao painel está desativado.")
    a.tentativas, a.bloqueado_ate, a.ultimo_acesso = 0, None, momento
    db.commit()
    return a


def criar_token(a: m.Administrador) -> str:
    momento = datetime.now(UTC)
    return jwt.encode(
        {"sub": a.id, "v": a.versao, "tipo": "plataforma",
         "iat": momento, "exp": momento + timedelta(hours=SESSAO_HORAS)},
        _chave(),
        algorithm="HS256",
    )  # fmt: skip


def do_token(db: Session, token: str | None) -> m.Administrador | None:
    if not token:
        return None
    try:
        dados = jwt.decode(token, _chave(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if dados.get("tipo") != "plataforma":
        return None
    a = db.get(m.Administrador, dados.get("sub"))
    if a is None or not a.ativo or a.versao != dados.get("v"):
        return None
    return a


def token_csrf(a: m.Administrador) -> str:
    mac = hmac.new(_chave().encode(), f"csrf:{a.id}:{a.versao}".encode(), hashlib.sha256)
    return base64.urlsafe_b64encode(mac.digest()).decode().rstrip("=")


def csrf_valido(a: m.Administrador, token: str) -> bool:
    return hmac.compare_digest(token_csrf(a), token or "")

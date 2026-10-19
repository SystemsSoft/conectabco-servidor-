"""Acesso aos portais do site (inquilino, proprietário): login pelo CPF/CNPJ
do contato com senha liberada pela equipe, bloqueio por tentativas, sessão
em token assinado e token CSRF. O `tipo` separa os portais: a sessão de um
não vale no outro."""

import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import jwt
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.errors import NaoEncontrado, RegraNegocio
from app.core.seguranca import _segredo, assinar, hash_senha, verificar_senha
from app.core.tempo import agora

TENTATIVAS = 5
BLOQUEIO = timedelta(minutes=15)
SESSAO_HORAS = 8
_SEM_CONFUSAO = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto or "")


def exigir_documento(contato, papel: str) -> str:
    login = digitos(contato.documento)
    if len(login) not in (11, 14):
        raise RegraNegocio(f"Cadastre o CPF/CNPJ do {papel}: ele é o login do portal.")
    return login


def liberar(db: Session, modelo, contato, papel: str):
    """Cria (ou renova) o acesso do contato com senha provisória; devolve
    (acesso, senha). A senha só existe aqui: a equipe entrega ao cliente."""
    login = exigir_documento(contato, papel)
    outro = db.scalar(sa.select(modelo).where(modelo.login == login))
    if outro and outro.contato_id != contato.id:
        raise RegraNegocio("Outro contato já usa este CPF/CNPJ no portal.")
    senha = "".join(secrets.choice(_SEM_CONFUSAO) for _ in range(10))
    acesso = db.scalar(sa.select(modelo).where(modelo.contato_id == contato.id))
    if acesso is None:
        acesso = modelo(id=str(uuid.uuid4()), contato_id=contato.id, versao=1)
        db.add(acesso)
    else:
        acesso.versao += 1  # derruba sessões abertas com a senha antiga
    acesso.login = login
    acesso.senha_hash = hash_senha(senha)
    acesso.ativo = True
    acesso.trocar_senha = True
    acesso.tentativas = 0
    acesso.bloqueado_ate = None
    db.commit()
    return acesso, senha


def revogar(db: Session, modelo, contato_id: str) -> None:
    acesso = db.scalar(sa.select(modelo).where(modelo.contato_id == contato_id))
    if acesso:
        db.delete(acesso)
        db.commit()


def autenticar(db: Session, modelo, login: str, senha: str):
    erro = RegraNegocio("CPF/CNPJ ou senha incorretos.")
    acesso = db.scalar(sa.select(modelo).where(modelo.login == digitos(login)))
    if acesso is None:
        verificar_senha(senha, hash_senha("x"))  # mesmo tempo de resposta
        raise erro
    momento = agora()
    if acesso.bloqueado_ate and acesso.bloqueado_ate > momento:
        raise RegraNegocio(
            "Muitas tentativas. Tente novamente em alguns minutos ou fale com a imobiliária."
        )
    if not verificar_senha(senha, acesso.senha_hash):
        acesso.tentativas += 1
        if acesso.tentativas >= TENTATIVAS:
            acesso.tentativas = 0
            acesso.bloqueado_ate = momento + BLOQUEIO
        db.commit()
        raise erro
    if not acesso.ativo:
        raise RegraNegocio("Seu acesso está desativado. Fale com a imobiliária.")
    acesso.tentativas = 0
    acesso.bloqueado_ate = None
    acesso.ultimo_acesso = momento
    db.commit()
    return acesso


def trocar_senha(db: Session, acesso, atual: str, nova: str, repetida: str) -> None:
    if not verificar_senha(atual, acesso.senha_hash):
        raise RegraNegocio("A senha atual não confere.")
    if len(nova) < 8:
        raise RegraNegocio("A nova senha deve ter pelo menos 8 caracteres.")
    if nova != repetida:
        raise RegraNegocio("As senhas novas não conferem.")
    if nova == atual:
        raise RegraNegocio("Escolha uma senha diferente da atual.")
    acesso.senha_hash = hash_senha(nova)
    acesso.trocar_senha = False
    acesso.versao += 1
    db.commit()


def criar_token(acesso, tipo: str) -> str:
    momento = datetime.now(UTC)
    return jwt.encode(
        {"sub": acesso.id, "v": acesso.versao, "tipo": tipo,
         "iat": momento, "exp": momento + timedelta(hours=SESSAO_HORAS)},
        _segredo(),
        algorithm="HS256",
    )  # fmt: skip


def acesso_do_token(db: Session, modelo, token: str | None, tipo: str):
    if not token:
        return None
    try:
        dados = jwt.decode(token, _segredo(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if dados.get("tipo") != tipo:
        return None
    acesso = db.get(modelo, dados.get("sub"))
    if acesso is None or not acesso.ativo or acesso.versao != dados.get("v"):
        return None
    return acesso


def token_csrf(acesso, tipo: str) -> str:
    return assinar(f"csrf-{tipo}:{acesso.id}:{acesso.versao}")


def obter_contato(db: Session, contato_id: str):
    from app.modules.crm.models import Contato

    contato = db.get(Contato, contato_id)
    if contato is None:
        raise NaoEncontrado("Contato não encontrado.")
    return contato

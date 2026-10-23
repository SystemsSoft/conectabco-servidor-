"""Senhas (PBKDF2-SHA256 com sal) e tokens de acesso (JWT).

Tokens e links são assinados com uma chave própria de cada imobiliária
(derivada do JWT_SECRET): o que uma emite não vale nas outras."""

import base64
import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from functools import lru_cache

import jwt

from app.core.config import get_settings
from app.core.imobiliarias import atual

_ITERACOES = 600_000


def hash_senha(senha: str) -> str:
    sal = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", senha.encode(), sal, _ITERACOES)
    return "pbkdf2_sha256${}${}${}".format(
        _ITERACOES,
        base64.b64encode(sal).decode(),
        base64.b64encode(dk).decode(),
    )


def verificar_senha(senha: str, guardado: str) -> bool:
    try:
        _, iteracoes, sal, dk = guardado.split("$")
        calculado = hashlib.pbkdf2_hmac(
            "sha256", senha.encode(), base64.b64decode(sal), int(iteracoes)
        )
        return hmac.compare_digest(calculado, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


@lru_cache
def _segredo() -> str:
    segredo = get_settings().jwt_secret
    if segredo:
        return segredo
    # Sem JWT_SECRET no .env os tokens valem só até o servidor reiniciar.
    return secrets.token_urlsafe(48)


def chave() -> str:
    """Chave de assinatura da imobiliária atual. A padrão (IMOBILIARIA_PADRAO,
    a de antes do multi-imobiliária) segue com o JWT_SECRET puro: logins,
    links e QR codes já impressos continuam valendo."""
    slug = atual().slug
    if slug == get_settings().imobiliaria_padrao:
        return _segredo()
    mac = hmac.new(_segredo().encode(), f"imobiliaria:{slug}".encode(), hashlib.sha256)
    return mac.hexdigest()


def criar_token(usuario_id: str, sessao_id: str) -> str:
    agora = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": usuario_id,
            "sid": sessao_id,
            "iat": agora,
            "exp": agora + timedelta(hours=get_settings().token_horas),
        },
        chave(),
        algorithm="HS256",
    )


def ler_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, chave(), algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


def assinar(texto: str) -> str:
    """Assinatura HMAC (links de arquivos que o navegador abre sem token)."""
    mac = hmac.new(chave().encode(), texto.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(mac).decode().rstrip("=")


def assinatura_valida(texto: str, assinatura: str) -> bool:
    return hmac.compare_digest(assinar(texto), assinatura)

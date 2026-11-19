"""Login com Google na área do representante, pelo Firebase Authentication.

O navegador abre o popup do Google com o SDK do Firebase e manda ao servidor
o ID token (JWT RS256 assinado pelo Google). Aqui ele é conferido com as
chaves públicas do Firebase (sem conta de serviço): assinatura, projeto,
emissor, validade e que o login foi mesmo pelo Google."""

from functools import lru_cache

import jwt

from app.core.config import get_settings
from app.core.errors import RegraNegocio

CHAVES = "https://www.googleapis.com/service_accounts/v1/jwk/securetoken@system.gserviceaccount.com"
SDK = "https://www.gstatic.com/firebasejs/12.6.0"


def configuracao() -> dict | None:
    """O firebaseConfig do app Web, para o navegador (None = sem Google)."""
    s = get_settings()
    if not (s.firebase_api_key and s.firebase_project_id):
        return None
    return {
        "apiKey": s.firebase_api_key,
        "authDomain": s.firebase_auth_domain or f"{s.firebase_project_id}.firebaseapp.com",
        "projectId": s.firebase_project_id,
        "appId": s.firebase_app_id,
    }


@lru_cache
def _cliente() -> jwt.PyJWKClient:
    # O Google troca as chaves de tempos em tempos; o cliente guarda por 1 h
    # e busca de novo quando aparece um "kid" desconhecido.
    return jwt.PyJWKClient(CHAVES, lifespan=3600, timeout=10)


def _chave_publica(token: str):
    return _cliente().get_signing_key_from_jwt(token).key


def conta_do_token(token: str) -> tuple[str, str]:
    """(uid, e-mail) da conta Google de um ID token do Firebase válido."""
    projeto = get_settings().firebase_project_id
    if not projeto:
        raise RegraNegocio("Login com Google indisponível.")
    if not token:
        raise RegraNegocio("Não foi possível confirmar a conta Google. Tente de novo.")
    try:
        dados = jwt.decode(
            token, _chave_publica(token), algorithms=["RS256"], audience=projeto,
            issuer=f"https://securetoken.google.com/{projeto}", leeway=60,
            options={"require": ["exp", "iat", "sub", "aud", "iss"]},
        )  # fmt: skip
    except (jwt.PyJWTError, ValueError) as e:
        raise RegraNegocio("Não foi possível confirmar a conta Google. Tente de novo.") from e
    if (dados.get("firebase") or {}).get("sign_in_provider") != "google.com" or not dados.get("sub"):
        raise RegraNegocio("Use uma conta Google.")
    return str(dados["sub"]), str(dados.get("email") or "")

"""Login obrigatório e permissões por módulo em toda a API."""

from datetime import timedelta
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.seguranca import ler_token
from app.core.tempo import agora

_bearer = HTTPBearer(auto_error=False)

# Ação exigida conforme o método HTTP (gravar exige criar ou editar).
_ACOES = {
    "GET": ("visualizar",),
    "PUT": ("criar", "editar"),
    "POST": ("criar", "editar"),
    "DELETE": ("excluir",),
}


def _negar(mensagem: str, codigo: int = status.HTTP_401_UNAUTHORIZED):
    raise HTTPException(codigo, detail=mensagem)


def usuario_logado(
    db: Annotated[Session, Depends(get_db)],
    credenciais: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
):
    """Valida o token e a sessão (que pode ter sido encerrada ou expirado
    por inatividade) e registra a atividade."""
    from app.modules.equipe.models import Sessao, Usuario
    from app.modules.equipe.services import configuracao

    if credenciais is None:
        _negar("Entre no sistema para continuar.")
    dados = ler_token(credenciais.credentials)
    if not dados:
        _negar("Sua sessão expirou. Entre novamente.")
    sessao = db.get(Sessao, dados.get("sid"))
    usuario = db.get(Usuario, dados.get("sub"))
    if sessao is None or usuario is None or sessao.usuario_id != usuario.id:
        _negar("Sua sessão foi encerrada. Entre novamente.")
    if not usuario.ativo:
        _negar("Seu usuário foi desativado.")
    momento = agora()
    limite = timedelta(minutes=configuracao(db).inatividade_minutos)
    if momento - sessao.ultima_atividade > limite:
        db.delete(sessao)
        db.commit()
        _negar("Sua sessão expirou por inatividade. Entre novamente.")
    if momento - sessao.ultima_atividade > timedelta(minutes=1):
        sessao.ultima_atividade = momento
        db.commit()
    return usuario


UsuarioLogado = Annotated[object, Depends(usuario_logado)]


def exigir_modulo(*modulos: str):
    """Dependência: o usuário precisa da ação (pelo método HTTP) em ao menos
    um dos módulos."""

    def verificar(request: Request, usuario: UsuarioLogado) -> None:
        acoes = _ACOES.get(request.method, ("visualizar",))
        if not any(usuario.pode(m, a) for m in modulos for a in acoes):
            from app.modules.equipe.enums import ModuloSistema

            nome = ModuloSistema(modulos[0]).rotulo
            verbo = {"visualizar": "ver", "excluir": "excluir"}.get(acoes[0], "gravar")
            _negar(
                f"Você não tem permissão para {verbo} em {nome}.",
                status.HTTP_403_FORBIDDEN,
            )

    return Depends(verificar)


def exigir_especial(usuario, especial: str, mensagem: str) -> None:
    if not usuario.tem_especial(especial):
        _negar(mensagem, status.HTTP_403_FORBIDDEN)

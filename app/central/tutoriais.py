"""Vídeos tutoriais do site da associação. Ficam no S3 (prefixo
plataforma/tutoriais/); como o bucket não é público, o site aponta para cá e
o servidor redireciona para um link assinado (vale 6 horas)."""

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, RedirectResponse

from app.central.painel import _so_pelo_servidor
from app.core.armazenamento import armazenamento
from app.core.errors import NaoEncontrado

router = APIRouter(prefix="/associacao/tutoriais", include_in_schema=False, dependencies=[Depends(_so_pelo_servidor)])

# Só os vídeos desta lista: o nome na URL nunca vira chave do bucket.
TUTORIAIS = {
    "como-contratar-o-sistema": "plataforma/tutoriais/como-contratar-o-sistema.mp4",
}


@router.get("/{nome}.mp4")
def tutorial(nome: str):
    chave = TUTORIAIS.get(nome)
    if chave is None:
        raise NaoEncontrado("Vídeo não encontrado.")
    loja = armazenamento()
    if url := loja.link(chave, "video/mp4", f"{nome}.mp4", True, "public, max-age=86400"):
        # O redirecionamento expira antes do link (6 h), para o navegador não reusar um vencido.
        return RedirectResponse(url, status_code=307, headers={"Cache-Control": "public, max-age=3600"})
    caminho = loja.caminho(chave)
    if not caminho.is_file():
        raise NaoEncontrado("Vídeo não encontrado.")
    return FileResponse(caminho, media_type="video/mp4")

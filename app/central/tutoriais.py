"""Vídeos tutoriais. Ficam no S3 (prefixo plataforma/tutoriais/); como o
bucket não é público, as páginas apontam para o servidor, que redireciona
para um link assinado (vale 6 horas).

- públicos (site da associação): /associacao/tutoriais/<nome>.mp4
- internos, só com login: /representante/tutorial.mp4 e /plataforma/tutorial.mp4
"""

import logging

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse, RedirectResponse, Response

from app.central.painel import _so_pelo_servidor
from app.core.armazenamento import armazenamento
from app.core.errors import NaoEncontrado

log = logging.getLogger(__name__)
PREFIXO = "plataforma/tutoriais/"

# Só os vídeos destas listas: o nome na URL nunca vira chave do bucket.
TUTORIAIS = {
    "como-contratar-o-sistema": PREFIXO + "como-contratar-o-sistema.mp4",
}
REPRESENTANTE = PREFIXO + "como-o-representante-cadastra-o-corretor.mp4"
PLATAFORMA = PREFIXO + "fluxo-de-implantacao-no-painel.mp4"

# Capítulos (segundo, título) ao lado dos vídeos internos.
CAPITULOS_REPRESENTANTE = [
    (18, "Entrar na área do representante"), (26, "Meus corretores"), (37, "Dados do corretor"),
    (71, "Endereço do site: domínio próprio ou subdomínio"), (94, "Tamanho da operação"),
    (112, "Contrato: gerar link ou anexar"), (138, "Enviar o link de assinatura"),
    (165, "Acompanhar a assinatura e a implantação"),
]  # fmt: skip
CAPITULOS_PLATAFORMA = [
    (15, "As três áreas do painel"), (33, "De onde vêm as solicitações"), (60, "Comercial: leads do site"),
    (78, "Comercial: funil"), (94, "Comercial: representantes"), (110, "Financeiro: solicitações"),
    (120, "Financeiro: contrato e documentos"), (140, "Confirmar o 1º pagamento"),
    (150, "Tecnologia: em implantação"), (169, "Implantar a imobiliária"), (190, "A imobiliária criada"),
    (205, "Comercial: receita"),
]  # fmt: skip


def disponivel(chave: str) -> bool:
    """O vídeo já foi enviado? (Com o S3 fora do ar, mostra o player assim mesmo.)"""
    try:
        return armazenamento().existe(chave)
    except Exception:  # noqa: BLE001
        log.warning("Não deu para conferir o tutorial %s no armazenamento", chave, exc_info=True)
        return True


def entregar(chave: str, publico: bool = False) -> Response:
    """Link assinado do S3 ou, no disco (desenvolvimento), o próprio arquivo."""
    if not disponivel(chave):  # sem isso, o link assinado levaria a um 404 do S3 e o player só ficaria parado
        raise NaoEncontrado("Vídeo não encontrado.")
    loja = armazenamento()
    visibilidade = "public" if publico else "private"
    if url := loja.link(chave, "video/mp4", chave.rsplit("/", 1)[-1], True, f"{visibilidade}, max-age=86400"):
        # O redirecionamento expira antes do link (6 h), para o navegador não reusar um vencido.
        return RedirectResponse(url, status_code=307, headers={"Cache-Control": f"{visibilidade}, max-age=3600"})
    return FileResponse(loja.caminho(chave), media_type="video/mp4")


router = APIRouter(prefix="/associacao/tutoriais", include_in_schema=False, dependencies=[Depends(_so_pelo_servidor)])


@router.get("/{nome}.mp4")
def tutorial(nome: str):
    if (chave := TUTORIAIS.get(nome)) is None:
        raise NaoEncontrado("Vídeo não encontrado.")
    return entregar(chave, publico=True)

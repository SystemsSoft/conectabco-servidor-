from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Form, UploadFile
from fastapi.responses import FileResponse
from pydantic import Field
from sqlalchemy.orm import Session

from app.core.auth import UsuarioLogado, exigir_modulo
from app.core.database import get_db
from app.core.errors import NaoEncontrado, RegraNegocio, validar_id
from app.core.schemas import Esquema
from app.modules.arquivos import services
from app.modules.arquivos.models import Arquivo

router = APIRouter(prefix="/arquivos", tags=["Arquivos"])
Db = Annotated[Session, Depends(get_db)]


class ArquivoSaida(Esquema):
    id: str
    nome: str
    categoria: str
    tipo_mime: str
    tamanho: int
    criado_em: datetime
    referencia: str = Field(description="Valor a guardar no cadastro (url)")
    link: str = Field(description="Caminho assinado para abrir o arquivo")


class PedidoLinks(Esquema):
    ids: list[str] = Field(max_length=500)


def _id_valido(i: str) -> bool:
    try:
        return validar_id(i) == i
    except RegraNegocio:
        return False


def _saida(a: Arquivo) -> ArquivoSaida:
    return ArquivoSaida(
        id=a.id,
        nome=a.nome,
        categoria=a.categoria,
        tipo_mime=a.tipo_mime,
        tamanho=a.tamanho,
        criado_em=a.criado_em,
        referencia=services.REFERENCIA + a.id,
        link=services.link(a.id),
    )


@router.post("", response_model=ArquivoSaida, status_code=201,
             dependencies=[exigir_modulo("cadastrosCrm")])  # fmt: skip
def enviar(
    arquivo: UploadFile,
    db: Db,
    usuario: UsuarioLogado,
    categoria: Annotated[str, Form(description="foto, video ou arquivo")],
):
    """Envia um arquivo do computador (multipart)."""
    novo = services.salvar(
        db, arquivo.file, arquivo.filename or "", categoria, usuario.id
    )
    return _saida(novo)


@router.post("/links", response_model=dict[str, str])
def links(pedido: PedidoLinks, db: Db, _: UsuarioLogado):
    """Links assinados para exibir/baixar (o navegador abre sem token).
    Ids inexistentes ficam de fora."""
    ids = {i for i in pedido.ids if _id_valido(i)}
    existentes = db.query(Arquivo.id).filter(Arquivo.id.in_(ids)).all() if ids else []
    return {i: services.link(i) for (i,) in existentes}


@router.get("/{arquivo_id}", response_model=ArquivoSaida)
def obter(arquivo_id: str, db: Db, _: UsuarioLogado):
    a = db.get(Arquivo, validar_id(arquivo_id))
    if a is None:
        raise NaoEncontrado("Arquivo não encontrado.")
    return _saida(a)


@router.get("/{arquivo_id}/conteudo", include_in_schema=False)
def conteudo(arquivo_id: str, expira: int, assinatura: str, db: Db):
    """Acesso pelo link assinado (imagens, vídeos com avanço, downloads)."""
    if not services.link_valido(arquivo_id, expira, assinatura):
        raise NaoEncontrado("Link expirado ou inválido.")
    a = db.get(Arquivo, validar_id(arquivo_id))
    caminho = services.caminho(arquivo_id) if a else None
    if a is None or not caminho.is_file():
        raise NaoEncontrado("Arquivo não encontrado.")
    return FileResponse(
        caminho,
        media_type=a.tipo_mime,
        filename=a.nome,
        content_disposition_type="inline"
        if services.exibivel(a.tipo_mime)
        else "attachment",
        headers={
            "Cache-Control": "private, max-age=3600",
            "X-Content-Type-Options": "nosniff",
        },
    )

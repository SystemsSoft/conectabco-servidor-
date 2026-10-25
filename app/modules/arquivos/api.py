from datetime import datetime
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Form, Query, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
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
    tarefas: BackgroundTasks,
):
    """Envia um arquivo do computador (multipart). As miniaturas das fotos
    são geradas em segundo plano, depois da resposta."""
    novo = services.salvar(
        db, arquivo.file, arquivo.filename or "", categoria, usuario.id
    )
    if novo.tipo_mime.startswith("image/"):
        tarefas.add_task(services.gerar_miniaturas, novo.id, novo.chave)
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
def conteudo(
    arquivo_id: str, expira: int, assinatura: str, db: Db,
    largura: Annotated[int | None, Query(ge=1, le=4000)] = None,
):  # fmt: skip
    """Acesso pelo link assinado (imagens, vídeos com avanço, downloads).
    Com `largura`, fotos saem como miniatura (bem mais leves para listas)."""
    if not services.link_valido(arquivo_id, expira, assinatura):
        raise NaoEncontrado("Link expirado ou inválido.")
    a = db.get(Arquivo, validar_id(arquivo_id))
    if a is None or not services.existe(a):
        raise NaoEncontrado("Arquivo não encontrado.")
    return resposta_arquivo(a, largura)


CACHE_ARQUIVO = "private, max-age=3600"
CACHE_MINIATURA = "private, max-age=604800, immutable"


def resposta_arquivo(a: Arquivo, largura: int | None = None, cache: str = CACHE_ARQUIVO):
    """O arquivo (ou a miniatura da foto, com `largura`). No S3, redireciona
    para um link assinado de curta duração: o S3 entrega o conteúdo (vídeos
    com avanço inclusive) e o bucket continua privado."""
    if not services.existe(a):
        raise NaoEncontrado("Arquivo não encontrado.")
    tipo, nome, inline = a.tipo_mime, a.nome, services.exibivel(a.tipo_mime)
    loja, chave = services.onde(a)
    if largura and a.tipo_mime.startswith("image/"):
        if mini := services.miniatura(a.id, a.chave, services.largura_miniatura(largura)):
            loja, chave = mini
            tipo, nome, inline, cache = "image/jpeg", f"{Path(a.nome).stem}.jpg", True, CACHE_MINIATURA
    if url := loja.link(chave, tipo, nome, inline, cache):
        # O redirecionamento vale menos que o link (que expira em horas).
        return RedirectResponse(url, status_code=307, headers={
            "Cache-Control": "private, max-age=600" if cache.startswith("private") else "public, max-age=3600",
            "Referrer-Policy": "no-referrer",
        })  # fmt: skip
    return FileResponse(
        loja.caminho(chave),
        media_type=tipo,
        filename=nome,
        content_disposition_type="inline" if inline else "attachment",
        headers={"Cache-Control": cache, "X-Content-Type-Options": "nosniff"},
    )

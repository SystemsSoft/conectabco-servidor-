"""Arquivos enviados (no S3, com chave ULID por imobiliária e por arquivo)
e links assinados para abri-los."""

import shutil
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from typing import BinaryIO

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.armazenamento import (
    S3,
    Disco,
    armazenamento,
    chave_miniatura,
    conferir,
    metadados,
    no_s3,
    nova_chave,
)
from app.core.armazenamento import temporario as armazenamento_temporario
from app.core.config import get_settings
from app.core.errors import NaoEncontrado, RegraNegocio
from app.core.imobiliarias import atual, com_imobiliaria
from app.core.seguranca import assinar, assinatura_valida
from app.core.tempo import agora
from app.modules.arquivos.models import Arquivo

MB = 1024 * 1024
REFERENCIA = "arquivo:"

# Tipo aceito por extensão (o tipo informado pelo navegador não é confiável).
_FOTOS = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
          "webp": "image/webp", "gif": "image/gif"}  # fmt: skip
_VIDEOS = {"mp4": "video/mp4", "m4v": "video/mp4", "mov": "video/quicktime",
           "webm": "video/webm"}  # fmt: skip
_DOCUMENTOS = {
    "pdf": "application/pdf",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "ppt": "application/vnd.ms-powerpoint",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "odt": "application/vnd.oasis.opendocument.text",
    "ods": "application/vnd.oasis.opendocument.spreadsheet",
    "txt": "text/plain",
    "csv": "text/csv",
    "zip": "application/zip",
    "dwg": "application/acad",
}
CATEGORIAS = {
    "foto": (_FOTOS, 15 * MB),
    "video": (_VIDEOS, 300 * MB),
    "arquivo": (_DOCUMENTOS | _FOTOS, 30 * MB),
}

# Assinaturas dos formatos de imagem (confere se é mesmo uma imagem).
_MAGICOS = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/gif": (b"GIF87a", b"GIF89a"),
}

# Abertos no navegador; os demais são baixados.
_EXIBIVEIS = ("image/", "video/", "application/pdf")


def _antigo(arquivo_id: str) -> tuple[Disco, str]:
    """Arquivo de antes do S3: pasta da imobiliária no disco do servidor."""
    return Disco(Path(get_settings().arquivos_dir)), f"{atual().slug}/{arquivo_id[:2]}/{arquivo_id}"


def _origem(arquivo_id: str, chave: str | None) -> tuple[Disco | S3, str]:
    """Onde está o conteúdo — sempre dentro da imobiliária atual."""
    if chave:
        return armazenamento(), conferir(chave)
    return _antigo(arquivo_id)


def existe(a: Arquivo) -> bool:
    try:
        if a.chave and no_s3():
            conferir(a.chave)
            return True  # gravado só depois do envio ao S3 (evita uma consulta por acesso)
        loja, chave = _origem(a.id, a.chave)
    except NaoEncontrado:
        return False
    return loja.existe(chave)


@contextmanager
def local(a: Arquivo) -> Iterator[Path]:
    """O arquivo no disco (cópia temporária, se estiver no S3)."""
    loja, chave = _origem(a.id, a.chave)
    with loja.local(chave) as caminho:
        yield caminho


def onde(a: Arquivo) -> tuple[Disco | S3, str]:
    """Armazenamento e chave do arquivo (para entregar ao navegador)."""
    return _origem(a.id, a.chave)


# Larguras das miniaturas de fotos (a tela pede a mais próxima).
LARGURAS = (320, 640, 1280)
_MINIATURAS_PRONTAS: set[str] = set()  # evita perguntar ao S3 se já existe


def largura_miniatura(pedida: int | None) -> int | None:
    """A menor largura padrão que atende ao pedido (ou nenhuma)."""
    if not pedida:
        return None
    return next((w for w in LARGURAS if w >= pedida), LARGURAS[-1])


def _chave_miniatura(arquivo_id: str, chave: str | None, largura: int) -> str:
    if chave:
        return chave_miniatura(chave, largura)
    return f"{atual().slug}/miniaturas/{arquivo_id[:2]}/{arquivo_id}-{largura}.jpg"


def miniatura(arquivo_id: str, chave: str | None, largura: int) -> tuple[Disco | S3, str] | None:
    """JPEG reduzido da foto (gerado uma vez e guardado junto do original).
    Corrige a rotação das fotos de celular. Nenhuma se não for uma imagem
    legível."""
    loja, original = _origem(arquivo_id, chave)
    destino = _chave_miniatura(arquivo_id, chave, largura)
    if destino in _MINIATURAS_PRONTAS or loja.existe(destino):
        _MINIATURAS_PRONTAS.add(destino)
        return loja, destino
    from PIL import Image, ImageOps

    temporario = armazenamento_temporario(".jpg")
    try:
        with loja.local(original) as origem, Image.open(origem) as img:
            img.draft("RGB", (largura * 2, largura * 2))  # JPEG: decodifica já reduzido
            img = ImageOps.exif_transpose(img)
            if getattr(img, "is_animated", False):
                img.seek(0)
            img.thumbnail((largura, largura * 4))
            if img.mode not in ("RGB", "L"):
                fundo = Image.new("RGB", img.size, (255, 255, 255))
                fundo.paste(img, mask=img.convert("RGBA").getchannel("A"))
                img = fundo
            img.save(temporario, "JPEG", quality=82, optimize=True, progressive=True)
        loja.gravar(destino, temporario, "image/jpeg", metadados(atual(), arquivo_id, "miniatura"))
    except (OSError, ValueError, Image.DecompressionBombError):
        return None
    finally:
        temporario.unlink(missing_ok=True)
    if len(_MINIATURAS_PRONTAS) > 20000:
        _MINIATURAS_PRONTAS.clear()
    _MINIATURAS_PRONTAS.add(destino)
    return loja, destino


def gerar_miniaturas(arquivo_id: str, chave: str | None) -> None:
    """Prepara as miniaturas em segundo plano logo após o envio da foto."""
    for largura in LARGURAS[:2]:
        miniatura(arquivo_id, chave, largura)


def remover_arquivo(a: Arquivo) -> None:
    """Apaga o conteúdo e as miniaturas (o registro fica com quem chamou)."""
    try:
        loja, chave = _origem(a.id, a.chave)
    except NaoEncontrado:
        return  # chave de outra imobiliária: não apaga nada
    for c in (chave, *(_chave_miniatura(a.id, a.chave, w) for w in LARGURAS)):
        loja.apagar(c)
        _MINIATURAS_PRONTAS.discard(c)


def exibivel(tipo_mime: str) -> bool:
    return tipo_mime.startswith(_EXIBIVEIS)


def _tipo(nome: str, categoria: str) -> tuple[str, int]:
    if categoria not in CATEGORIAS:
        raise RegraNegocio("Categoria inválida (use foto, video ou arquivo).")
    tipos, limite = CATEGORIAS[categoria]
    extensao = nome.rsplit(".", 1)[-1].lower() if "." in nome else ""
    if extensao not in tipos:
        aceitos = ", ".join(sorted(tipos)).upper()
        raise RegraNegocio(f"Formato não aceito. Envie: {aceitos}.")
    return tipos[extensao], limite


def _confere_imagem(tipo: str, inicio: bytes) -> bool:
    if tipo == "image/webp":
        return inicio[:4] == b"RIFF" and inicio[8:12] == b"WEBP"
    return any(inicio.startswith(m) for m in _MAGICOS.get(tipo, (b"",)))


def salvar(
    db: Session, conteudo: BinaryIO, nome: str, categoria: str, usuario_id: str
) -> Arquivo:
    """Grava o arquivo em partes, sem passar do limite da categoria."""
    nome = Path(nome or "").name.strip()[:255]
    if not nome:
        raise RegraNegocio("Arquivo sem nome.")
    tipo, limite = _tipo(nome, categoria)
    novo = Arquivo(
        id=str(uuid.uuid4()),
        nome=nome,
        categoria=categoria,
        tipo_mime=tipo,
        enviado_por_id=usuario_id,
        criado_em=agora(),
    )
    temporario = armazenamento_temporario()
    tamanho = 0
    try:
        with temporario.open("wb") as saida:
            while parte := conteudo.read(MB):
                if tamanho == 0 and tipo.startswith("image/"):
                    if not _confere_imagem(tipo, parte):
                        raise RegraNegocio("O arquivo não é uma imagem válida.")
                tamanho += len(parte)
                if tamanho > limite:
                    raise RegraNegocio(
                        f"Arquivo grande demais (máximo {limite // MB} MB "
                        f"para {categoria}s)."
                    )
                saida.write(parte)
        if tamanho == 0:
            raise RegraNegocio("O arquivo está vazio.")
        novo.chave = nova_chave(categoria)
        armazenamento().gravar(novo.chave, temporario, tipo, metadados(atual(), novo.id, categoria))
    finally:
        temporario.unlink(missing_ok=True)
    novo.tamanho = tamanho
    _registrar(db, novo)
    return novo


def _registrar(db: Session, novo: Arquivo) -> None:
    """Grava o registro; se não der, o conteúdo enviado não fica solto."""
    db.add(novo)
    try:
        db.commit()
    except Exception:
        db.rollback()
        armazenamento().apagar(novo.chave)
        raise


def duplicar(db: Session, original: Arquivo, nome: str, usuario_id: str | None) -> Arquivo:
    """Cópia independente do arquivo (outro ULID, mesma imobiliária)."""
    copia = Arquivo(
        id=str(uuid.uuid4()), nome=nome[:255], categoria=original.categoria,
        tipo_mime=original.tipo_mime, tamanho=original.tamanho,
        enviado_por_id=usuario_id, criado_em=agora(), chave=nova_chave(original.categoria),
    )  # fmt: skip
    dados = metadados(atual(), copia.id, copia.categoria)
    loja, chave = _origem(original.id, original.chave)
    if original.chave:
        loja.copiar(chave, copia.chave, dados)
    else:  # de antes do S3: copia do disco para o armazenamento atual
        temporario = armazenamento_temporario()
        try:
            with loja.local(chave) as caminho:
                shutil.copyfile(caminho, temporario)
            armazenamento().gravar(copia.chave, temporario, copia.tipo_mime, dados)
        finally:
            temporario.unlink(missing_ok=True)
    _registrar(db, copia)
    return copia


def migrar_para_armazenamento(db: Session) -> tuple[int, int]:
    """Leva os arquivos de antes do S3 (pasta no disco) para o armazenamento
    atual, um a um, com chave ULID. Devolve (levados, sem conteúdo no disco).
    Os originais ficam na pasta antiga (apague depois de conferir)."""
    levados = faltando = 0
    for a in db.scalars(sa.select(Arquivo).where(Arquivo.chave.is_(None))).all():
        disco, antigo = _antigo(a.id)
        if not disco.existe(antigo):
            faltando += 1
            continue
        chave = nova_chave(a.categoria)
        temporario = armazenamento_temporario()
        try:
            shutil.copyfile(disco.caminho(antigo), temporario)
            armazenamento().gravar(chave, temporario, a.tipo_mime, metadados(atual(), a.id, a.categoria))
        finally:
            temporario.unlink(missing_ok=True)
        a.chave = chave
        try:
            db.commit()
        except Exception:
            db.rollback()
            armazenamento().apagar(chave)
            raise
        levados += 1
    return levados, faltando


def link(arquivo_id: str, validade_s: int | None = None) -> str:
    """Caminho assinado (relativo ao servidor), válido pelo tempo do login."""
    validade_s = validade_s or get_settings().token_horas * 3600
    expira = int(time.time()) + validade_s
    assinatura = assinar(f"{arquivo_id}:{expira}")
    return com_imobiliaria(
        f"/api/v1/arquivos/{arquivo_id}/conteudo"
        f"?expira={expira}&assinatura={assinatura}"
    )


def link_valido(arquivo_id: str, expira: int, assinatura: str) -> bool:
    return expira >= time.time() and assinatura_valida(
        f"{arquivo_id}:{expira}", assinatura
    )


def limpar_orfaos(db: Session, carencia: timedelta = timedelta(days=1)) -> int:
    """Apaga os arquivos que nenhum cadastro usa mais (anexo removido ou
    imóvel excluído). A carência poupa envios de cadastros ainda abertos."""
    from app.modules.crm.models import Anexo
    from app.modules.auditoria.models import MidiaAuditoria
    from app.modules.financeiro.models import DocumentoFinanceiro
    from app.modules.inquilino.models import ArquivoContrato

    referencia = sa.literal(REFERENCIA, sa.String) + Arquivo.id
    em_imovel = sa.select(Anexo.id).where(Anexo.url == referencia)
    em_contrato = sa.select(ArquivoContrato.id).where(ArquivoContrato.arquivo_id == Arquivo.id)
    em_auditoria = sa.select(MidiaAuditoria.id).where(MidiaAuditoria.arquivo_id == Arquivo.id)
    em_financeiro = sa.select(DocumentoFinanceiro.id).where(
        DocumentoFinanceiro.arquivo_id == Arquivo.id
    )
    orfaos = db.scalars(
        sa.select(Arquivo).where(
            Arquivo.criado_em <= agora() - carencia,
            ~sa.exists(em_imovel),
            ~sa.exists(em_contrato),
            ~sa.exists(em_auditoria),
            ~sa.exists(em_financeiro),
        )
    ).all()
    for a in orfaos:
        remover_arquivo(a)
        db.delete(a)
    db.commit()
    return len(orfaos)

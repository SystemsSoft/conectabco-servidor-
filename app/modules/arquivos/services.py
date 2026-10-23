"""Armazenamento dos arquivos enviados e links assinados para abri-los."""

import os
import time
import uuid
from datetime import timedelta
from pathlib import Path
from typing import BinaryIO

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import RegraNegocio
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


def pasta() -> Path:
    """Pasta da imobiliária atual (cada uma tem a sua)."""
    return atual().pasta_arquivos


def caminho(arquivo_id: str) -> Path:
    return pasta() / arquivo_id[:2] / arquivo_id


# Larguras das miniaturas de fotos (a tela pede a mais próxima).
LARGURAS = (320, 640, 1280)


def largura_miniatura(pedida: int | None) -> int | None:
    """A menor largura padrão que atende ao pedido (ou nenhuma)."""
    if not pedida:
        return None
    return next((w for w in LARGURAS if w >= pedida), LARGURAS[-1])


def caminho_miniatura(arquivo_id: str, largura: int) -> Path:
    return pasta() / "miniaturas" / arquivo_id[:2] / f"{arquivo_id}-{largura}.jpg"


def miniatura(arquivo_id: str, largura: int) -> Path | None:
    """JPEG reduzido da foto (gerado uma vez e guardado em disco). Corrige a
    rotação das fotos de celular. Nenhuma se não for uma imagem legível."""
    destino = caminho_miniatura(arquivo_id, largura)
    if destino.is_file():
        return destino
    origem = caminho(arquivo_id)
    if not origem.is_file():
        return None
    from PIL import Image, ImageOps

    try:
        with Image.open(origem) as img:
            img.draft("RGB", (largura * 2, largura * 2))  # JPEG: decodifica já reduzido
            img = ImageOps.exif_transpose(img)
            if getattr(img, "is_animated", False):
                img.seek(0)
            img.thumbnail((largura, largura * 4))
            if img.mode not in ("RGB", "L"):
                fundo = Image.new("RGB", img.size, (255, 255, 255))
                fundo.paste(img, mask=img.convert("RGBA").getchannel("A"))
                img = fundo
            destino.parent.mkdir(parents=True, exist_ok=True)
            temporario = destino.with_suffix(f".{uuid.uuid4().hex}.parcial")
            img.save(temporario, "JPEG", quality=82, optimize=True, progressive=True)
            os.replace(temporario, destino)
    except (OSError, ValueError, Image.DecompressionBombError):
        return None
    return destino


def gerar_miniaturas(arquivo_id: str) -> None:
    """Prepara as miniaturas em segundo plano logo após o envio da foto."""
    for largura in LARGURAS[:2]:
        miniatura(arquivo_id, largura)


def remover_arquivo(arquivo_id: str) -> None:
    caminho(arquivo_id).unlink(missing_ok=True)
    for largura in LARGURAS:
        caminho_miniatura(arquivo_id, largura).unlink(missing_ok=True)


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
    destino = caminho(novo.id)
    destino.parent.mkdir(parents=True, exist_ok=True)
    temporario = destino.with_suffix(".parcial")
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
        os.replace(temporario, destino)
    finally:
        temporario.unlink(missing_ok=True)
    novo.tamanho = tamanho
    db.add(novo)
    try:
        db.commit()
    except Exception:
        destino.unlink(missing_ok=True)
        raise
    return novo


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
        remover_arquivo(a.id)
        db.delete(a)
    db.commit()
    return len(orfaos)

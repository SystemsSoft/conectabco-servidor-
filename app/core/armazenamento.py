"""Onde ficam as fotos, vídeos e documentos enviados.

Produção: o bucket S3 (ARQUIVOS_ARMAZENAMENTO=s3, bucket AWS_BUCKET).
Desenvolvimento e testes: a pasta ARQUIVOS_DIR, com as mesmas chaves.

Chaves (ULID: único e em ordem de criação):
  imobiliarias/<ULID da imobiliária>/<categoria>/<ULID do arquivo>
  imobiliarias/<ULID da imobiliária>/miniaturas/<ULID do arquivo>-<largura>.jpg

O ULID da imobiliária fica no banco central, é único e não muda: nenhum
objeto é compartilhado entre imobiliárias, e toda leitura confere antes se a
chave é da imobiliária da requisição (conferir)."""

import logging
import shutil
import unicodedata
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote

from app.core.config import get_settings
from app.core.errors import NaoEncontrado, RegraNegocio
from app.core.imobiliarias import Imobiliaria, atual
from app.core.ulid import novo_ulid, ulid_valido

log = logging.getLogger("armazenamento")


class ArmazenamentoIndisponivel(RegraNegocio):
    """O arquivo não pôde ser guardado (S3 fora do ar ou sem permissão): quem
    chamou desfaz o que gravou e a pessoa pode tentar de novo."""

    status_code = 503

    def __init__(self):
        super().__init__("Não foi possível guardar o arquivo agora. Tente de novo em alguns minutos; "
                         "se continuar, fale com a associação.")  # fmt: skip

RAIZ = "imobiliarias"
MINIATURAS = "miniaturas"
# Validade dos links do S3 (o navegador pede partes do vídeo durante a reprodução).
VALIDADE_LINK = 6 * 3600


def prefixo(imob: Imobiliaria) -> str:
    if not ulid_valido(imob.chave):
        raise RuntimeError(f"Imobiliária '{imob.slug}' sem chave de arquivos: rode gerenciar.py migrar.")
    return f"{RAIZ}/{imob.chave}/"


def nova_chave(categoria: str) -> str:
    """Chave de um arquivo novo da imobiliária atual."""
    return f"{prefixo(atual())}{categoria}/{novo_ulid()}"


def conferir(chave: str) -> str:
    """A chave é da imobiliária da requisição? Se não for, é como se o
    arquivo não existisse (e fica registrado: é um erro de dados)."""
    partes = chave.split("/")
    if not (chave.startswith(prefixo(atual())) and len(partes) == 4 and ulid_valido(partes[3])):
        log.error("Chave de arquivo fora da imobiliária %s: %s", atual().slug, chave)
        raise NaoEncontrado("Arquivo não encontrado.")
    return chave


def chave_miniatura(chave: str, largura: int) -> str:
    raiz, imob, _, arquivo = chave.split("/")
    return f"{raiz}/{imob}/{MINIATURAS}/{arquivo}-{largura}.jpg"


def disposicao(nome: str, inline: bool) -> str:
    """Content-Disposition com o nome original (acentos inclusive)."""
    simples = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode()
    simples = simples.replace('"', "").replace("\\", "") or "arquivo"
    return f"{'inline' if inline else 'attachment'}; filename=\"{simples}\"; filename*=UTF-8''{quote(nome)}"


def pasta_temporaria() -> Path:
    """Envios em andamento (no disco, não na memória: vídeos de até 300 MB)."""
    pasta = Path(get_settings().arquivos_dir) / ".envios"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


def temporario(sufixo: str = "") -> Path:
    return pasta_temporaria() / f"{uuid.uuid4().hex}{sufixo}.parcial"


class Disco:
    """Pasta local (desenvolvimento e testes)."""

    def __init__(self, raiz: Path):
        self.raiz = raiz

    def caminho(self, chave: str) -> Path:
        return self.raiz / chave

    def gravar(self, chave: str, origem: Path, tipo: str, metadados: dict[str, str]) -> None:
        destino = self.caminho(chave)
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(origem, destino)

    def existe(self, chave: str) -> bool:
        return self.caminho(chave).is_file()

    def apagar(self, chave: str) -> None:
        self.caminho(chave).unlink(missing_ok=True)

    def copiar(self, de: str, para: str, metadados: dict[str, str]) -> None:
        destino = self.caminho(para)
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.caminho(de), destino)

    @contextmanager
    def local(self, chave: str) -> Iterator[Path]:
        caminho = self.caminho(chave)
        if not caminho.is_file():
            raise FileNotFoundError(chave)
        yield caminho

    def link(self, chave: str, tipo: str, nome: str, inline: bool, cache: str) -> str | None:
        return None  # o servidor entrega o arquivo da pasta


class S3:
    """Bucket privado: o servidor grava e apaga; o navegador baixa direto do
    S3 por links assinados de curta duração."""

    def __init__(self, bucket: str, cliente):
        self.bucket = bucket
        self.cliente = cliente

    def gravar(self, chave: str, origem: Path, tipo: str, metadados: dict[str, str]) -> None:
        try:
            # Em partes, para os vídeos grandes.
            self.cliente.upload_file(str(origem), self.bucket, chave,
                                     ExtraArgs={"ContentType": tipo, "Metadata": metadados})  # fmt: skip
        finally:
            origem.unlink(missing_ok=True)

    def existe(self, chave: str) -> bool:
        try:
            self.cliente.head_object(Bucket=self.bucket, Key=chave)
        except Exception as e:
            if _nao_encontrado(e):
                return False
            raise
        return True

    def apagar(self, chave: str) -> None:
        self.cliente.delete_object(Bucket=self.bucket, Key=chave)

    def copiar(self, de: str, para: str, metadados: dict[str, str]) -> None:
        self.cliente.copy_object(Bucket=self.bucket, Key=para, CopySource={"Bucket": self.bucket, "Key": de},
                                 Metadata=metadados, MetadataDirective="REPLACE")  # fmt: skip

    @contextmanager
    def local(self, chave: str) -> Iterator[Path]:
        """Cópia temporária no disco (miniaturas, transcrição dos vídeos)."""
        destino = temporario()
        try:
            try:
                self.cliente.download_file(self.bucket, chave, str(destino))
            except Exception as e:
                if _nao_encontrado(e):
                    raise FileNotFoundError(chave) from e
                raise
            yield destino
        finally:
            destino.unlink(missing_ok=True)

    def link(self, chave: str, tipo: str, nome: str, inline: bool, cache: str) -> str | None:
        return self.cliente.generate_presigned_url("get_object", ExpiresIn=VALIDADE_LINK, Params={
            "Bucket": self.bucket, "Key": chave, "ResponseContentType": tipo,
            "ResponseContentDisposition": disposicao(nome, inline), "ResponseCacheControl": cache,
        })  # fmt: skip


def _nao_encontrado(e: Exception) -> bool:
    codigo = getattr(e, "response", {}).get("Error", {}).get("Code", "")
    return codigo in ("404", "NoSuchKey", "NotFound")


@lru_cache
def _s3(bucket: str) -> S3:
    from app.core import aws

    s = get_settings()
    try:  # links assinados precisam da região do bucket
        regiao = aws.cliente("s3", "us-east-1").get_bucket_location(Bucket=bucket)
        regiao = regiao.get("LocationConstraint") or "us-east-1"
    except Exception:  # noqa: BLE001 - sem s3:GetBucketLocation, a região do .env
        regiao = s.aws_regiao
    cliente = aws.cliente("s3", regiao, signature_version="s3v4", s3={"addressing_style": "virtual"})
    return S3(bucket, cliente)


def armazenamento() -> Disco | S3:
    s = get_settings()
    if s.arquivos_armazenamento == "s3":
        return _s3(s.aws_bucket)
    return Disco(Path(s.arquivos_dir))


def no_s3() -> bool:
    return get_settings().arquivos_armazenamento == "s3"


def metadados(imob: Imobiliaria, arquivo_id: str, categoria: str) -> dict[str, str]:
    """Gravados com o objeto: dizem de quem ele é mesmo fora do sistema."""
    return {"imobiliaria": imob.chave, "imobiliaria-slug": imob.slug,
            "arquivo": arquivo_id, "categoria": categoria}  # fmt: skip

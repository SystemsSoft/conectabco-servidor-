"""Arquivos no S3 (com um S3 falso): chaves ULID por imobiliária e por
arquivo, links assinados do bucket, miniaturas, cópia, remoção, a trava contra
chaves de outra imobiliária e a migração dos arquivos de antes do S3."""

import io
import re
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from botocore.exceptions import ClientError

from app.core import armazenamento
from app.core.config import get_settings
from app.core.imobiliarias import usar
from app.core.tempo import agora
from app.core.ulid import novo_ulid, ulid_valido
from app.modules.arquivos import services
from app.modules.arquivos.models import Arquivo
from tests.apoio import novo_id

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
PDF = b"%PDF-1.4 contrato"
ULID = r"[0-9A-HJKMNP-TV-Z]{26}"


class S3Falso:
    def __init__(self):
        self.objetos: dict[str, tuple[bytes, str, dict]] = {}

    def upload_file(self, origem, bucket, chave, ExtraArgs):
        assert bucket == "associacao-conecta"
        self.objetos[chave] = (Path(origem).read_bytes(), ExtraArgs["ContentType"], ExtraArgs["Metadata"])

    def head_object(self, Bucket, Key):
        if Key not in self.objetos:
            raise ClientError({"Error": {"Code": "404"}}, "HeadObject")

    def delete_object(self, Bucket, Key):
        self.objetos.pop(Key, None)

    def copy_object(self, Bucket, Key, CopySource, Metadata, MetadataDirective):
        conteudo, tipo, _ = self.objetos[CopySource["Key"]]
        self.objetos[Key] = (conteudo, tipo, Metadata)

    def download_file(self, bucket, chave, destino):
        if chave not in self.objetos:
            raise ClientError({"Error": {"Code": "404"}}, "GetObject")
        Path(destino).write_bytes(self.objetos[chave][0])

    def generate_presigned_url(self, operacao, ExpiresIn, Params):
        extra = {k: v for k, v in Params.items() if k.startswith("Response")}
        return f"https://s3.teste/{Params['Key']}?{urlencode(extra)}"


@pytest.fixture
def s3(monkeypatch, tmp_path) -> S3Falso:
    s = get_settings()
    monkeypatch.setattr(s, "arquivos_armazenamento", "s3")
    monkeypatch.setattr(s, "arquivos_dir", str(tmp_path))
    falso = S3Falso()
    monkeypatch.setattr(armazenamento, "_s3", lambda bucket: armazenamento.S3(bucket, falso))
    services._MINIATURAS_PRONTAS.clear()
    return falso


def _enviar(client, nome, conteudo, categoria):
    r = client.post("/api/v1/arquivos", data={"categoria": categoria}, files={"arquivo": (nome, conteudo)})
    assert r.status_code == 201, r.text
    return r.json()


def _redireciona(client, link) -> tuple[str, dict]:
    r = client.get(link, follow_redirects=False)
    assert r.status_code == 307 and r.headers["referrer-policy"] == "no-referrer"
    destino = urlsplit(r.headers["location"])
    return destino.path.removeprefix("/"), {k: v[0] for k, v in parse_qs(destino.query).items()}


def test_envio_vai_para_o_s3_com_chaves_ulid(client, banco, imobiliaria, s3, tmp_path):
    foto = _enviar(client, "fachada.png", PNG, "foto")
    with banco() as db:
        chave = db.get(Arquivo, foto["id"]).chave
    assert re.fullmatch(rf"imobiliarias/{imobiliaria.chave}/foto/{ULID}", chave)
    conteudo, tipo, meta = s3.objetos[chave]
    assert (conteudo, tipo) == (PNG, "image/png")
    assert meta == {"imobiliaria": imobiliaria.chave, "imobiliaria-slug": imobiliaria.slug,
                    "arquivo": foto["id"], "categoria": "foto"}  # fmt: skip
    # Nada fica no disco do servidor (nem o envio em andamento).
    assert not [p for p in tmp_path.rglob("*") if p.is_file()]

    # O link do app redireciona para um link assinado do bucket (privado).
    assert _redireciona(client, foto["link"]) == (chave, {
        "ResponseContentType": "image/png",
        "ResponseContentDisposition": "inline; filename=\"fachada.png\"; filename*=UTF-8''fachada.png",
        "ResponseCacheControl": "private, max-age=3600",
    })  # fmt: skip
    doc = _enviar(client, "relatório.pdf", PDF, "arquivo")
    _, params = _redireciona(client, doc["link"])
    assert params["ResponseContentDisposition"] == (
        "inline; filename=\"relatorio.pdf\"; filename*=UTF-8''relat%C3%B3rio.pdf")
    assert client.get(foto["link"].replace("assinatura=", "assinatura=x")).status_code == 404


def test_miniaturas_ficam_no_s3(client, imobiliaria, s3):
    from PIL import Image

    saida = io.BytesIO()
    Image.new("RGB", (1600, 900), (40, 120, 200)).save(saida, "JPEG")
    foto = _enviar(client, "sala.jpg", saida.getvalue(), "foto")
    prefixo = f"imobiliarias/{imobiliaria.chave}/miniaturas/"
    geradas = sorted(c for c in s3.objetos if c.startswith(prefixo))
    assert [c.rsplit("-", 1)[1] for c in geradas] == ["320.jpg", "640.jpg"]  # logo após o envio
    chave, params = _redireciona(client, foto["link"] + "&largura=300")
    assert chave == geradas[0] and params["ResponseContentType"] == "image/jpeg"
    assert "immutable" in params["ResponseCacheControl"]
    chave, _ = _redireciona(client, foto["link"] + "&largura=1000")  # gerada na hora
    assert chave.endswith("-1280.jpg") and s3.objetos[chave][1] == "image/jpeg"


def test_chave_de_outra_imobiliaria_nunca_abre(client, banco, imobiliaria, nova_imobiliaria, s3):
    outra = nova_imobiliaria("outra", "Outra Imobiliária")
    assert outra.chave != imobiliaria.chave
    foto = _enviar(client, "f.png", PNG, "foto")
    alheia = f"imobiliarias/{outra.chave}/foto/{novo_ulid()}"
    s3.objetos[alheia] = (b"da outra", "image/png", {})
    with banco() as db:  # registro corrompido apontando para a outra imobiliária
        db.get(Arquivo, foto["id"]).chave = alheia
        db.commit()
    assert client.get(foto["link"], follow_redirects=False).status_code == 404
    with usar(imobiliaria), banco() as db:
        services.remover_arquivo(db.get(Arquivo, foto["id"]))
    assert alheia in s3.objetos  # e nunca apaga o que não é dela


def test_copia_local_e_remocao(banco, imobiliaria, s3):
    with usar(imobiliaria), banco() as db:
        original = services.salvar(db, io.BytesIO(PDF), "contrato.pdf", "arquivo", None)
        copia = services.duplicar(db, original, "contrato (cópia).pdf", None)
        assert copia.chave != original.chave and ulid_valido(copia.chave.rsplit("/", 1)[1])
        assert s3.objetos[copia.chave][0] == PDF
        assert s3.objetos[copia.chave][2]["arquivo"] == copia.id
        with services.local(copia) as caminho:  # ex.: transcrição dos vídeos
            assert caminho.read_bytes() == PDF
        assert not caminho.exists()
        services.remover_arquivo(original)
    assert original.chave not in s3.objetos and copia.chave in s3.objetos


def test_migra_os_arquivos_de_antes_do_s3(client, banco, imobiliaria, s3, tmp_path):
    antigos = {"com_conteudo": novo_id(), "sem_conteudo": novo_id()}
    with banco() as db:
        for i in antigos.values():
            db.add(Arquivo(id=i, nome="planta.pdf", categoria="arquivo", tipo_mime="application/pdf",
                           tamanho=len(PDF), criado_em=agora()))  # fmt: skip
        db.commit()
    pasta_antiga = tmp_path / imobiliaria.slug / antigos["com_conteudo"][:2]
    pasta_antiga.mkdir(parents=True)
    (pasta_antiga / antigos["com_conteudo"]).write_bytes(PDF)

    # Até migrar, continua abrindo da pasta antiga.
    with usar(imobiliaria):
        link = services.link(antigos["com_conteudo"])
    assert client.get(link).content == PDF

    with usar(imobiliaria), banco() as db:
        assert services.migrar_para_armazenamento(db) == (1, 1)
        chave = db.get(Arquivo, antigos["com_conteudo"]).chave
        assert services.migrar_para_armazenamento(db) == (0, 1)  # pode repetir
    assert re.fullmatch(rf"imobiliarias/{imobiliaria.chave}/arquivo/{ULID}", chave)
    assert s3.objetos[chave][0] == PDF and s3.objetos[chave][2]["arquivo"] == antigos["com_conteudo"]
    assert (pasta_antiga / antigos["com_conteudo"]).is_file()  # o original fica
    assert _redireciona(client, link)[0] == chave


def test_ulid():
    ids = [novo_ulid() for _ in range(1000)]
    assert len(set(ids)) == 1000 and all(map(ulid_valido, ids))
    assert ids[0][:10] <= ids[-1][:10]  # começa pelo instante: ordena por data
    assert not ulid_valido("01ARZ3NDEKTSV4RRFFQ69G5FAU")  # U não existe no alfabeto

"""Vídeos tutoriais do site: link assinado do S3 ou arquivo do disco."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.central import tutoriais
from app.core.config import get_settings
from app.main import create_app

CAMINHO = "/associacao/tutoriais/como-contratar-o-sistema.mp4"


def test_no_disco(plataforma):
    with TestClient(create_app()) as c:
        assert c.get(CAMINHO).status_code == 404  # ainda não enviado
        arquivo = Path(get_settings().arquivos_dir) / tutoriais.TUTORIAIS["como-contratar-o-sistema"]
        arquivo.parent.mkdir(parents=True)
        arquivo.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        r = c.get(CAMINHO)
        assert r.status_code == 200 and r.headers["content-type"] == "video/mp4"
        assert c.get("/associacao/tutoriais/outro.mp4").status_code == 404


def test_no_s3_redireciona_para_link_assinado(plataforma, monkeypatch):
    pedidos = []

    class S3Falso:
        def link(self, chave, tipo, nome, inline, cache):
            pedidos.append((chave, tipo, inline))
            return "https://associacao-conecta.s3.amazonaws.com/assinado"

    monkeypatch.setattr(tutoriais, "armazenamento", S3Falso)
    with TestClient(create_app()) as c:
        r = c.get(CAMINHO, follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "https://associacao-conecta.s3.amazonaws.com/assinado"
    assert "max-age=3600" in r.headers["cache-control"]
    assert pedidos == [("plataforma/tutoriais/como-contratar-o-sistema.mp4", "video/mp4", True)]

from datetime import timedelta

import pytest

from app.core.config import get_settings
from app.modules.arquivos import services
from app.modules.equipe.enums import PerfilAcesso, permissoes_do_perfil
from tests.apoio import novo_id

URL = "/api/v1/arquivos"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


@pytest.fixture(autouse=True)
def pasta_temporaria(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "arquivos_dir", str(tmp_path))
    return tmp_path


def _enviar(client, nome, conteudo, categoria="foto", tipo="application/octet-stream"):
    return client.post(URL, data={"categoria": categoria},
                       files={"arquivo": (nome, conteudo, tipo)})  # fmt: skip


def test_envia_e_abre_pelo_link_assinado(client):
    r = _enviar(client, "fachada.png", PNG)
    assert r.status_code == 201, r.text
    a = r.json()
    assert (a["nome"], a["tipoMime"], a["tamanho"]) == ("fachada.png", "image/png", len(PNG))
    assert a["referencia"] == f"arquivo:{a['id']}"

    aberto = client.get(a["link"])
    assert aberto.status_code == 200 and aberto.content == PNG
    assert aberto.headers["content-type"] == "image/png"
    assert aberto.headers["content-disposition"].startswith("inline")
    # Vídeos avançam por partes (Range).
    parcial = client.get(a["link"], headers={"Range": "bytes=0-7"})
    assert parcial.status_code == 206 and parcial.content == PNG[:8]

    adulterado = a["link"].replace("assinatura=", "assinatura=x")
    assert client.get(adulterado).status_code == 404
    expirado = services.link(a["id"], validade_s=-10)
    assert client.get(expirado).json()["detail"] == "Link expirado ou inválido."

    links = client.post(f"{URL}/links", json={"ids": [a["id"], novo_id(), "../x"]}).json()
    assert list(links) == [a["id"]]
    assert client.get(f"{URL}/{a['id']}").json()["categoria"] == "foto"
    # Sem login não envia nem pede links; o link assinado basta para abrir.
    sem_login = {"Authorization": "Bearer invalido"}
    assert client.post(f"{URL}/links", json={"ids": []}, headers=sem_login).status_code == 401


def test_documento_e_video(client):
    pdf = _enviar(client, "Matrícula.PDF", b"%PDF-1.7 ...", "arquivo").json()
    assert pdf["tipoMime"] == "application/pdf"
    planilha = _enviar(client, "custos.xlsx", b"PK\x03\x04...", "arquivo").json()
    aberto = client.get(planilha["link"])
    assert aberto.headers["content-disposition"].startswith("attachment")
    video = _enviar(client, "tour.mp4", b"\x00\x00\x00\x18ftypmp42", "video").json()
    assert video["tipoMime"] == "video/mp4"


def test_validacoes(client, monkeypatch):
    def erro(*args, **kw):
        return _enviar(client, *args, **kw).json()["detail"]

    assert erro("script.html", b"<script>", "arquivo").startswith("Formato não aceito")
    assert erro("tour.mp4", b"...", "foto").startswith("Formato não aceito. Envie: GIF")
    assert erro("falsa.jpg", b"<html>", "foto") == "O arquivo não é uma imagem válida."
    assert erro("vazio.pdf", b"", "arquivo") == "O arquivo está vazio."
    assert erro("a.png", PNG, "musica") == "Categoria inválida (use foto, video ou arquivo)."
    monkeypatch.setitem(services.CATEGORIAS, "foto", (services._FOTOS, 50))
    assert erro("grande.png", PNG) == "Arquivo grande demais (máximo 0 MB para fotos)."
    assert not list(get_settings().arquivos_dir and services.pasta().rglob("*.parcial"))


def test_corretor_envia_mas_sem_cadastros_nao(client):
    client.put(f"/api/v1/equipe/usuarios/{novo_id()}", json={
        "nome": "Financeiro", "login": "fin", "perfil": "financeiro",
        "permissoes": permissoes_do_perfil(PerfilAcesso.financeiro),
        "senha": "senha-do-financeiro"})  # fmt: skip
    r = client.post("/api/v1/auth/entrar", json={"usuario": "fin", "senha": "senha-do-financeiro"})
    client.headers["Authorization"] = f"Bearer {r.json()['token']}"
    assert _enviar(client, "a.png", PNG).status_code == 403


def test_limpa_os_que_nenhum_imovel_usa(client, banco):
    usado = _enviar(client, "usada.png", PNG).json()
    solto = _enviar(client, "solta.png", PNG).json()
    imovel = {"titulo": "Casa", "anexos": [
        {"tipo": "foto", "titulo": "Fachada", "url": usado["referencia"]},
        {"tipo": "link", "titulo": "Tour", "url": "https://exemplo.com/tour"}]}  # fmt: skip
    assert client.put(f"/api/v1/crm/imoveis/{novo_id()}", json=imovel).status_code in (200, 201)

    with banco() as db:
        assert services.limpar_orfaos(db) == 0  # ainda na carência
        assert services.limpar_orfaos(db, carencia=timedelta(0)) == 1
    assert client.get(f"{URL}/{solto['id']}").status_code == 404
    assert not services.caminho(solto["id"]).exists()
    assert client.get(usado["link"]).content == PNG

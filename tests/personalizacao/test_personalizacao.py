import base64

from app.modules.equipe.enums import PerfilAcesso, permissoes_do_perfil
from tests.apoio import novo_id

URL = "/api/v1/personalizacao"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


def _corretor(client):
    client.put(f"/api/v1/equipe/usuarios/{novo_id()}", json={
        "nome": "Corretor", "login": "corretor", "perfil": "corretor",
        "permissoes": permissoes_do_perfil(PerfilAcesso.corretor),
        "senha": "senha-do-corretor"})  # fmt: skip
    r = client.post("/api/v1/auth/entrar", json={"usuario": "corretor", "senha": "senha-do-corretor"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_dados_padrao_e_gravacao(client):
    assert client.get(f"{URL}/empresa").json()["creci"] == "CRECI 065655 RJ"
    dados = {"nome": "Marcelo Bonifácio Imóveis", "atividade": "Corretor de Imóveis",
             "creci": "CRECI 065655 RJ", "documento": "11.222.333/0001-81",
             "endereco": "Rua Moreira César, 100 - Icaraí, Niterói/RJ",
             "telefone": "(21) 99999-0000", "chavePix": "11222333000181"}  # fmt: skip
    r = client.put(f"{URL}/empresa", json=dados).json()
    assert r["nome"] == "Marcelo Bonifácio Imóveis" and r["temLogo"] is False
    assert client.put(f"{URL}/empresa", json=dados | {"documento": "123"}).json()["detail"] == (
        "CNPJ/CPF inválido.")


def test_logo(client):
    assert client.get(f"{URL}/logo").status_code == 404
    r = client.put(f"{URL}/logo", json={"tipo": "image/png", "base64": base64.b64encode(PNG).decode()})
    assert r.json()["temLogo"] is True
    assert base64.b64decode(client.get(f"{URL}/logo").json()["base64"]) == PNG
    gif = base64.b64encode(b"GIF89a....").decode()
    assert client.put(f"{URL}/logo", json={"tipo": "image/gif", "base64": gif}).json()["detail"] == (
        "Use uma imagem PNG ou JPG.")
    grande = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"0" * (2 * 1024 * 1024)).decode()
    assert client.put(f"{URL}/logo", json={"tipo": "image/png", "base64": grande}).json()["detail"] == (
        "O logotipo deve ter no máximo 2 MB.")
    assert client.delete(f"{URL}/logo").json()["temLogo"] is False


def test_corretor_le_mas_nao_altera(client):
    h = _corretor(client)
    assert client.get(f"{URL}/empresa", headers=h).status_code == 200
    r = client.put(f"{URL}/empresa", headers=h, json={"nome": "X"})
    assert r.status_code == 403

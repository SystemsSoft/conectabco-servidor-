import re

import pytest

from app.core.config import get_settings
from tests.apoio import contato, imovel, novo_id

URL = "/api/v1/financeiro"
PDF = b"%PDF-1.4 boleto"
XLSX = b"PK\x03\x04 planilha"


@pytest.fixture(autouse=True)
def pasta_arquivos(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "arquivos_dir", str(tmp_path))


def _pasta(client, nome="Boletos") -> str:
    id = novo_id()
    r = client.put(f"{URL}/pastas/{id}", json={"nome": nome})
    assert r.status_code == 201, r.text
    return id


def _enviar(client, pasta, nome="Boleto Outubro.pdf", conteudo=PDF):
    return client.post(f"{URL}/pastas/{pasta}/documentos", files={"arquivo": (nome, conteudo)})


def test_pastas_criar_renomear_e_nome_unico(client):
    boletos = _pasta(client, "Boletos")
    _pasta(client, "Relatórios")
    assert client.put(f"{URL}/pastas/{novo_id()}", json={"nome": " boletos "}).json()["detail"] == (
        'Já existe uma pasta chamada "boletos".'
    )
    assert client.put(f"{URL}/pastas/{novo_id()}", json={"nome": "  "}).json()["detail"] == (
        "Informe o nome da pasta."
    )
    r = client.put(f"{URL}/pastas/{boletos}", json={"nome": "Boletos 2026"})
    assert (r.status_code, r.json()["nome"]) == (200, "Boletos 2026")
    assert [p["nome"] for p in client.get(f"{URL}/pastas").json()] == ["Boletos 2026", "Relatórios"]


def test_documentos_enviar_renomear_mover_substituir_e_excluir(client):
    boletos, relatorios = _pasta(client, "Boletos"), _pasta(client, "Relatórios")
    r = _enviar(client, boletos)
    assert r.status_code == 201, r.text
    doc = r.json()
    assert (doc["nome"], doc["arquivoNome"], doc["tamanho"]) == ("Boleto Outubro", "Boleto Outubro.pdf", len(PDF))
    assert _enviar(client, boletos, "Relatório.docx", b"PK docx").status_code == 201
    assert client.get(f"{URL}/pastas").json()[0]["documentos"] == 2

    # Só PDF, Word e Excel.
    assert "não é aceito" in _enviar(client, boletos, "foto.png", b"\x89PNG\r\n\x1a\n").json()["detail"]
    assert "não é aceito" in _enviar(client, boletos, "nota.txt", b"oi").json()["detail"]

    # Renomeia e move.
    r = client.put(f"{URL}/documentos/{doc['id']}", json={"nome": "Boleto aluguel", "pastaId": relatorios})
    assert (r.json()["nome"], r.json()["pastaId"]) == ("Boleto aluguel", relatorios)
    assert [d["nome"] for d in client.get(f"{URL}/pastas/{relatorios}/documentos").json()] == ["Boleto aluguel"]

    # Substitui o arquivo: o antigo deixa de existir.
    antigo = doc["arquivoId"]
    r = client.post(f"{URL}/documentos/{doc['id']}/arquivo", files={"arquivo": ("Planilha.xlsx", XLSX)})
    novo = r.json()
    assert (novo["nome"], novo["arquivoNome"], novo["tamanho"]) == ("Boleto aluguel", "Planilha.xlsx", len(XLSX))
    assert client.get(f"/api/v1/arquivos/{antigo}").status_code == 404
    links = client.post("/api/v1/arquivos/links", json={"ids": [novo["arquivoId"]]}).json()
    assert client.get(links[novo["arquivoId"]]).content == XLSX

    # Exclui o documento e depois a pasta com o que sobrou.
    assert client.delete(f"{URL}/documentos/{doc['id']}").status_code == 204
    assert client.get(f"/api/v1/arquivos/{novo['arquivoId']}").status_code == 404
    assert client.delete(f"{URL}/pastas/{boletos}").status_code == 204
    assert [p["nome"] for p in client.get(f"{URL}/pastas").json()] == ["Relatórios"]
    assert client.get(f"{URL}/pastas/{boletos}/documentos").status_code == 404


def test_documentos_nao_sao_apagados_como_orfaos(client, banco):
    from datetime import timedelta

    from app.modules.arquivos.services import limpar_orfaos

    pasta = _pasta(client)
    arquivo = _enviar(client, pasta).json()["arquivoId"]
    with banco() as db:
        limpar_orfaos(db, carencia=timedelta(0))
    assert client.get(f"/api/v1/arquivos/{arquivo}").status_code == 200


# ------------------------------------------------------------ Compartilhamento


def _entrar_proprietario(client, dono, cpf):
    senha = client.post(f"/api/v1/auditorias/proprietarios/{dono}/acesso").json()["senha"]
    client.post("/proprietario/entrar", data={"documento": cpf, "senha": senha})
    csrf = re.search(r'name="csrf" value="([^"]+)"', client.get("/proprietario/senha").text).group(1)
    client.post("/proprietario/senha", data={"atual": senha, "nova": "senha-do-dono-1",
                                             "repetida": "senha-do-dono-1", "csrf": csrf})  # fmt: skip


def _entrar_inquilino(client, inquilino, cpf):
    senha = client.post(f"/api/v1/portal-inquilino/acessos/{inquilino}").json()["senha"]
    client.post("/inquilino/entrar", data={"documento": cpf, "senha": senha})
    csrf = re.search(r'name="csrf" value="([^"]+)"', client.get("/inquilino/senha").text).group(1)
    client.post("/inquilino/senha", data={"atual": senha, "nova": "senha-nova-123",
                                          "repetida": "senha-nova-123", "csrf": csrf})  # fmt: skip


def test_compartilhar_pasta_com_inquilinos_e_proprietarios(client):
    dono = contato(client, "Roberto Dono", documento="111.444.777-35", papeis=["proprietario"])
    inquilina = contato(client, "Ana Inquilina", documento="529.982.247-25", papeis=["locatario"])
    lead = contato(client, "Lead Qualquer", papeis=["lead"])
    r = client.put(f"/api/v1/locacao/contratos/{novo_id()}", json={
        "imovelId": imovel(client, finalidades=["locacao"]), "locatarioId": inquilina,
        "beneficiarios": [{"contatoId": dono, "percentual": 100}],
        "dataInicio": "2026-01-01", "valorAluguel": 3000, "diaVencimento": 10})  # fmt: skip
    assert r.status_code == 201, r.text

    dest = {d["nome"]: d for d in client.get(f"{URL}/destinatarios").json()}
    assert set(dest) == {"Roberto Dono", "Ana Inquilina"}
    assert (dest["Roberto Dono"]["proprietario"], dest["Roberto Dono"]["inquilino"]) == (True, False)
    assert dest["Ana Inquilina"]["inquilino"] and not dest["Ana Inquilina"]["acessoInquilino"]

    boletos, privada = _pasta(client, "Boletos"), _pasta(client, "Interna")
    doc = _enviar(client, boletos).json()["id"]
    interno = _enviar(client, privada, "Interno.pdf").json()["id"]

    url = f"{URL}/pastas/{boletos}/compartilhamento"
    assert client.put(url, json={"contatoIds": [lead]}).json()["detail"] == (
        "O contato escolhido não é inquilino nem proprietário."
    )
    r = client.put(url, json={"contatoIds": [dono, inquilina]})
    assert r.status_code == 200, r.text
    assert set(r.json()["compartilhadaCom"]) == {dono, inquilina}
    pastas = {p["nome"]: p for p in client.get(f"{URL}/pastas").json()}
    assert set(pastas["Boletos"]["compartilhadaCom"]) == {dono, inquilina}
    assert pastas["Interna"]["compartilhadaCom"] == []

    # Na Área do proprietário: só a pasta compartilhada e os documentos dela.
    _entrar_proprietario(client, dono, "111.444.777-35")
    pagina = client.get("/proprietario/documentos").text
    assert "Boletos" in pagina and "Boleto Outubro" in pagina and "Interna" not in pagina
    assert client.get(f"/proprietario/documento/{doc}").content == PDF
    assert client.get(f"/proprietario/documento/{interno}").status_code == 404

    # Na Área do inquilino: a pasta aparece em Documentos.
    _entrar_inquilino(client, inquilina, "529.982.247-25")
    pagina = client.get("/inquilino/documentos").text
    assert "Boletos" in pagina and f"/inquilino/documento/{doc}" in pagina and "Interna" not in pagina
    assert client.get(f"/inquilino/documento/{doc}").content == PDF
    assert client.get(f"/inquilino/documento/{interno}").status_code == 404

    # Tirar da lista corta o acesso na hora.
    assert client.put(url, json={"contatoIds": [inquilina]}).json()["compartilhadaCom"] == [inquilina]
    assert client.get(f"/proprietario/documento/{doc}").status_code == 404
    assert client.get(f"/inquilino/documento/{doc}").status_code == 200
    assert "Nenhum documento foi compartilhado" in client.get("/proprietario/documentos").text

    # Excluir a pasta apaga o compartilhamento junto.
    assert client.delete(f"{URL}/pastas/{boletos}").status_code == 204
    assert client.get(f"/inquilino/documento/{doc}").status_code == 404
    assert "Boleto Outubro" not in client.get("/inquilino/documentos").text


def test_acesso_ao_portal_sem_contrato_so_com_cpf(client):
    """Inquilino e proprietário sem contrato: basta o CPF/CNPJ para liberar,
    e eles veem as pastas compartilhadas."""
    inq = contato(client, "Igor Interessado", documento="529.982.247-25", papeis=["locatario"])
    dono = contato(client, "Olga Proprietária", documento="111.444.777-35", papeis=["proprietario"])
    sem_cpf = contato(client, "Sem Documento", papeis=["proprietario"])
    assert client.post(f"/api/v1/auditorias/proprietarios/{sem_cpf}/acesso").json()["detail"].startswith(
        "Cadastre o CPF"
    )

    pasta = _pasta(client, "Avaliações")
    doc = _enviar(client, pasta, "Laudo.pdf").json()["id"]
    client.put(f"{URL}/pastas/{pasta}/compartilhamento", json={"contatoIds": [inq, dono]})

    # Proprietário sem contrato aparece na lista das Auditorias (sem números).
    donos = {p["nome"]: p for p in client.get("/api/v1/auditorias/proprietarios").json()}
    assert donos["Olga Proprietária"]["contratosAtivos"] == 0
    assert donos["Olga Proprietária"]["acesso"] is None

    _entrar_proprietario(client, dono, "111.444.777-35")
    assert client.get("/api/v1/auditorias/proprietarios").json()[0]["acesso"] is not None
    assert "Nenhum contrato ativo no momento" in client.get("/proprietario").text
    assert "Avaliações" in client.get("/proprietario/documentos").text
    assert client.get(f"/proprietario/documento/{doc}").content == PDF

    _entrar_inquilino(client, inq, "529.982.247-25")
    assert "Nenhum contrato de locação ainda" in client.get("/inquilino").text
    assert "Nenhum contrato de locação ainda" in client.get("/inquilino/pagamentos").text
    pagina = client.get("/inquilino/documentos").text
    assert "Avaliações" in pagina and "Laudo" in pagina and "Fotos e vídeos" not in pagina
    assert client.get("/inquilino/avisos").status_code == 200
    assert client.get(f"/inquilino/documento/{doc}").content == PDF


def test_duplicar_documento(client):
    pasta = _pasta(client)
    doc = _enviar(client, pasta, "Liquidação 20102026.pdf").json()
    url = f"{URL}/documentos/{doc['id']}/duplicar"

    r = client.post(url)
    assert r.status_code == 201, r.text
    copia = r.json()
    assert (copia["nome"], copia["arquivoNome"], copia["pastaId"]) == (
        "Liquidação 20102026 (cópia)", "Liquidação 20102026 (cópia).pdf", pasta)
    assert copia["arquivoId"] != doc["arquivoId"] and copia["tamanho"] == doc["tamanho"]
    assert client.post(url).json()["nome"] == "Liquidação 20102026 (cópia 2)"

    # A cópia é independente: excluir o original não apaga o arquivo dela.
    assert client.delete(f"{URL}/documentos/{doc['id']}").status_code == 204
    links = client.post("/api/v1/arquivos/links", json={"ids": [copia["arquivoId"]]}).json()
    assert client.get(links[copia["arquivoId"]]).content == PDF
    assert {d["nome"] for d in client.get(f"{URL}/pastas/{pasta}/documentos").json()} == {
        "Liquidação 20102026 (cópia)", "Liquidação 20102026 (cópia 2)"}
    assert client.post(f"{URL}/documentos/{novo_id()}/duplicar").status_code == 404

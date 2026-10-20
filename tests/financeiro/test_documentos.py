from tests.apoio import novo_id

URL = "/api/v1/financeiro"
PDF = b"%PDF-1.4 boleto"
XLSX = b"PK\x03\x04 planilha"


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

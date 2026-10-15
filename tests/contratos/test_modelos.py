from tests.apoio import novo_id

URL = "/api/v1/contratos/modelos"


def _modelo(**extra):
    return {
        "nome": "Locação residencial (padrão)", "tipo": "locacao",
        "texto": "CONTRATO DE LOCAÇÃO\n{{locador_nome}} ... foro de {{foro_cidade}}.",
        "parametros": [{"chave": "foro_cidade", "rotulo": "Cidade do foro",
                        "valorPadrao": "Niterói"}],
        "baseId": "pronto-locacao-residencial", **extra,
    }  # fmt: skip


def test_crud_com_parametros(client):
    id = novo_id()
    r = client.put(f"{URL}/{id}", json=_modelo())
    assert r.status_code == 201
    j = r.json()
    assert j["parametros"] == [{"chave": "foro_cidade", "rotulo": "Cidade do foro",
                                "tipo": "texto", "valorPadrao": "Niterói",
                                "descricao": ""}]  # fmt: skip
    assert j["baseId"] == "pronto-locacao-residencial" and j["atualizadoEm"]
    client.put(f"{URL}/{novo_id()}", json=_modelo(nome="Venda", tipo="venda"))
    assert [m["nome"] for m in client.get(URL, params={"tipo": "venda"}).json()] == ["Venda"]
    texto_longo = "x" * 100_000
    assert client.put(f"{URL}/{id}", json=_modelo(texto=texto_longo)).status_code == 200


def test_validacoes(client):
    r = client.put(f"{URL}/{novo_id()}", json=_modelo(nome=" "))
    assert r.json()["detail"] == "Informe o nome."
    r = client.put(f"{URL}/{novo_id()}", json=_modelo(parametros=[
        {"chave": "Foro Cidade", "rotulo": "x"}]))  # fmt: skip
    assert r.json()["detail"].startswith("Chave inválida")
    r = client.put(f"{URL}/{novo_id()}", json=_modelo(parametros=[
        {"chave": "a", "rotulo": "x"}, {"chave": "a", "rotulo": "y"}]))  # fmt: skip
    assert r.json()["detail"] == "Há parâmetros com a mesma chave."


def test_mantem_um_modelo_de_locacao(client):
    a, b = novo_id(), novo_id()
    client.put(f"{URL}/{a}", json=_modelo())
    r = client.delete(f"{URL}/{a}")
    assert r.json()["detail"].startswith("Mantenha ao menos um modelo de locação")
    # Mudar o único de locação para outro tipo também é recusado.
    assert client.put(f"{URL}/{a}", json=_modelo(tipo="outros")).status_code == 422
    client.put(f"{URL}/{b}", json=_modelo(nome="Comercial"))
    assert client.delete(f"{URL}/{a}").status_code == 204
    # Modelos de outros tipos podem ser excluídos à vontade.
    c = novo_id()
    client.put(f"{URL}/{c}", json=_modelo(tipo="outros"))
    assert client.delete(f"{URL}/{c}").status_code == 204

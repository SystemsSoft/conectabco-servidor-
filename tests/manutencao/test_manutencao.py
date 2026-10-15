from tests.apoio import imovel, novo_id

URL = "/api/v1/manutencoes"


def _registro(**extra):
    return {
        "id": novo_id(), "data": "2026-10-05", "profissional": "João Pintor",
        "servico": "Pintura da sala", "material": "Tinta", "valorMaterial": 300,
        "valorMaoDeObra": 700, "valorTaxa": 100, **extra,
    }  # fmt: skip


def test_pauta_com_diario(client):
    id = novo_id()
    dados = {
        "contexto": "locacao", "imovelId": imovel(client), "tipo": "pintura",
        "descricao": "Pintar a sala", "dataPrevista": "2026-10-20",
        "diario": [_registro()],
    }  # fmt: skip
    r = client.put(f"{URL}/{id}", json=dados)
    assert r.status_code == 201
    assert r.json()["diario"][0]["valorTaxa"] == 100

    segundo = _registro(profissional="Maria", valorTaxa=0)
    r = client.put(f"{URL}/{id}", json=dados | {"status": "emAndamento",
                                                "diario": [dados["diario"][0], segundo]})  # fmt: skip
    assert [d["profissional"] for d in r.json()["diario"]] == ["João Pintor", "Maria"]

    r = client.put(f"{URL}/{id}", json=dados | {"diario": [segundo]})
    assert len(r.json()["diario"]) == 1

    assert client.get(URL, params={"contexto": "venda"}).json()["total"] == 0
    assert client.get(URL, params={"contexto": "locacao"}).json()["total"] == 1
    assert client.delete(f"{URL}/{id}").status_code == 204


def test_validacoes(client):
    base = {"contexto": "venda", "imovelId": imovel(client), "tipo": "outros",
            "descricao": "Trocar portão"}  # fmt: skip
    r = client.put(f"{URL}/{novo_id()}", json=base)
    assert r.json()["detail"] == "Informe qual o tipo de manutenção."
    r = client.put(f"{URL}/{novo_id()}", json=base | {"tipo": "alvenaria",
                                                      "diario": [_registro(profissional=" ")]})  # fmt: skip
    assert r.json()["detail"] == "Informe o profissional."

URL = "/api/v1/crm/imoveis"


def _imovel(**extra):
    return {
        "titulo": "Apartamento na Barra",
        "finalidades": ["venda", "locacao"],
        "tipo": "apartamento",
        "bairro": "Barra da Tijuca",
        "cidade": "Rio de Janeiro",
        "uf": "RJ",
        "valorVenda": 1250000,
        "quartos": 3,
        "comodidades": ["Piscina", "Piscina", " Academia "],
        "personalizadas": [{"nome": "Pé-direito", "valor": "4 m"}],
        "anexos": [{"tipo": "foto", "titulo": "Sala", "url": "https://x/1.jpg"}],
        **extra,
    }


def test_cria_com_codigo_sequencial_e_json_camel_case(client):
    r1 = client.post(URL, json=_imovel())
    r2 = client.post(URL, json=_imovel(titulo="Casa no Recreio"))
    assert r1.status_code == 201
    a, b = r1.json(), r2.json()
    assert (a["codigo"], b["codigo"]) == ("IM-0001", "IM-0002")
    assert a["valorVenda"] == 1250000
    assert a["finalidades"] == ["venda", "locacao"]
    assert a["comodidades"] == ["Piscina", "Academia"]
    assert a["personalizadas"] == [{"nome": "Pé-direito", "valor": "4 m"}]
    assert a["anexos"][0]["url"] == "https://x/1.jpg"
    assert a["criadoEm"] and a["id"]


def test_atualiza_substituindo_listas_e_mantendo_codigo(client):
    criado = client.post(URL, json=_imovel()).json()
    r = client.put(
        f"{URL}/{criado['id']}",
        json=_imovel(titulo="Novo título", finalidades=["temporada"], anexos=[]),
    )
    assert r.status_code == 200
    novo = r.json()
    assert novo["codigo"] == criado["codigo"]
    assert novo["titulo"] == "Novo título"
    assert novo["finalidades"] == ["temporada"]
    assert novo["anexos"] == []


def test_regras_de_negocio(client):
    r = client.post(URL, json=_imovel(finalidades=[]))
    assert r.status_code == 422
    assert r.json()["detail"] == "Selecione ao menos uma finalidade."

    r = client.post(URL, json=_imovel(titulo="  "))
    assert r.json()["detail"] == "Informe o título do imóvel."

    r = client.post(URL, json=_imovel(proprietarioId="nao-existe"))
    assert r.json()["detail"] == "Proprietário não encontrado."

    assert client.get(f"{URL}/xyz").status_code == 404


def test_filtros_e_paginacao(client):
    client.post(URL, json=_imovel())
    client.post(URL, json=_imovel(titulo="Sala Centro", finalidades=["locacao"],
                                  tipo="sala", bairro="Centro"))  # fmt: skip
    client.post(URL, json=_imovel(titulo="Casa", finalidades=["venda"],
                                  status="vendido"))  # fmt: skip

    assert client.get(URL).json()["total"] == 3
    assert client.get(URL, params={"finalidade": "locacao"}).json()["total"] == 2
    assert client.get(URL, params={"status": "vendido"}).json()["total"] == 1
    assert client.get(URL, params={"tipo": "sala"}).json()["total"] == 1
    assert client.get(URL, params={"busca": "centro"}).json()["total"] == 1
    assert client.get(URL, params={"busca": "IM-0002"}).json()["total"] == 1

    pagina = client.get(URL, params={"limite": 2, "deslocamento": 2}).json()
    assert (pagina["total"], len(pagina["itens"])) == (3, 1)


def test_enum_invalido_e_rejeitado(client):
    assert client.post(URL, json=_imovel(tipo="castelo")).status_code == 422


def test_remover_desvincula_agenda(client):
    imovel = client.post(URL, json=_imovel()).json()
    evento = client.post(
        "/api/v1/crm/eventos",
        json={"titulo": "Visita", "tipo": "visita",
              "dataHora": "2026-10-20T10:00:00", "imovelId": imovel["id"]},
    ).json()  # fmt: skip
    assert client.delete(f"{URL}/{imovel['id']}").status_code == 204
    assert client.get(f"{URL}/{imovel['id']}").status_code == 404
    assert client.get(f"/api/v1/crm/eventos/{evento['id']}").json()["imovelId"] is None

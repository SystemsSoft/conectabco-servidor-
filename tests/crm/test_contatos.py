URL = "/api/v1/crm/contatos"


def _contato(**extra):
    return {
        "nome": "Ana Souza",
        "papeis": ["lead", "comprador"],
        "celular": "(21) 99999-0000",
        "email": "ana@exemplo.com",
        "etapa": "visita",
        "origem": "instagram",
        "dataNascimento": "1990-05-10",
        "perfil": {
            "finalidade": "venda",
            "tipos": ["apartamento", "cobertura"],
            "cidade": "Rio de Janeiro",
            "bairros": "Barra da Tijuca, Recreio",
            "valorMin": 800000,
            "valorMax": 1500000,
            "quartosMin": 3,
            "comodidades": ["Piscina"],
        },
        **extra,
    }


def test_cria_e_le_com_perfil(client):
    r = client.post(URL, json=_contato())
    assert r.status_code == 201
    c = client.get(f"{URL}/{r.json()['id']}").json()
    assert c["papeis"] == ["lead", "comprador"]
    assert c["dataNascimento"] == "1990-05-10"
    assert c["perfil"]["tipos"] == ["apartamento", "cobertura"]
    assert c["perfil"]["valorMax"] == 1500000


def test_atualiza_e_remove_perfil(client):
    c = client.post(URL, json=_contato()).json()
    r = client.put(f"{URL}/{c['id']}", json=_contato(nome="Ana S.", perfil=None))
    assert r.json()["nome"] == "Ana S."
    assert r.json()["perfil"] is None


def test_validacoes(client):
    perfil = _contato()["perfil"] | {"valorMin": 2000000}
    r = client.post(URL, json=_contato(perfil=perfil))
    assert r.status_code == 422
    assert r.json()["detail"] == "O valor mínimo é maior que o máximo."
    assert client.post(URL, json=_contato(nome=" ")).json()["detail"] == (
        "Informe o nome do contato."
    )


def test_filtros(client):
    client.post(URL, json=_contato())
    client.post(URL, json=_contato(nome="Bruno Dono", papeis=["proprietario"],
                                   perfil=None, etapa="novo"))  # fmt: skip
    assert client.get(URL, params={"papel": "proprietario"}).json()["total"] == 1
    assert client.get(URL, params={"comPerfil": True}).json()["total"] == 1
    assert client.get(URL, params={"etapa": "visita"}).json()["total"] == 1
    nomes = [c["nome"] for c in client.get(URL).json()["itens"]]
    assert nomes == ["Ana Souza", "Bruno Dono"]


def test_remover_desvincula_imoveis_e_agenda(client):
    dono = client.post(URL, json=_contato(papeis=["proprietario"])).json()
    imovel = client.post(
        "/api/v1/crm/imoveis",
        json={"titulo": "Casa", "proprietarioId": dono["id"]},
    ).json()
    evento = client.post(
        "/api/v1/crm/eventos",
        json={"titulo": "Recado", "tipo": "anotacao", "contatoId": dono["id"]},
    ).json()
    assert client.delete(f"{URL}/{dono['id']}").status_code == 204
    imovel = client.get(f"/api/v1/crm/imoveis/{imovel['id']}").json()
    assert imovel["proprietarioId"] is None
    evento = client.get(f"/api/v1/crm/eventos/{evento['id']}").json()
    assert evento["contatoId"] is None

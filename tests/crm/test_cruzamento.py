BASE = "/api/v1/crm"


def _setup(client):
    ana = client.post(f"{BASE}/contatos", json={
        "nome": "Ana",
        "perfil": {"finalidade": "venda", "tipos": ["apartamento"],
                   "bairros": "Barra da Tijuca", "valorMax": 1500000,
                   "quartosMin": 3, "comodidades": ["Piscina"]},
    }).json()  # fmt: skip
    client.post(f"{BASE}/contatos", json={"nome": "Sem perfil"})
    barra = client.post(f"{BASE}/imoveis", json={
        "titulo": "Apto Barra", "finalidades": ["venda"], "tipo": "apartamento",
        "bairro": "Barra da Tijuca", "valorVenda": 1250000, "quartos": 3,
        "comodidades": ["piscina"],
    }).json()  # fmt: skip
    client.post(f"{BASE}/imoveis", json={
        "titulo": "Loja Centro", "finalidades": ["venda"], "tipo": "loja",
        "bairro": "Centro", "valorVenda": 3000000,
    })  # fmt: skip
    client.post(f"{BASE}/imoveis", json={
        "titulo": "Vendido", "finalidades": ["venda"], "tipo": "apartamento",
        "status": "vendido", "bairro": "Barra da Tijuca", "valorVenda": 1000000,
        "quartos": 3,
    })  # fmt: skip
    return ana, barra


def test_sugere_imoveis_para_contato(client):
    ana, barra = _setup(client)
    r = client.get(f"{BASE}/cruzamento/contatos/{ana['id']}").json()
    assert [s["imovelId"] for s in r] == [barra["id"]]
    assert r[0]["score"] == 100
    assert "Bairro: Barra da Tijuca" in r[0]["atende"]


def test_sugere_contatos_para_imovel_e_resumo(client):
    ana, barra = _setup(client)
    r = client.get(f"{BASE}/cruzamento/imoveis/{barra['id']}").json()
    assert [s["contatoNome"] for s in r] == ["Ana"]
    resumo = client.get(f"{BASE}/cruzamento/resumo").json()
    assert resumo == {"totalSugestoes": 1, "contatosComPerfil": 1,
                      "imoveisDisponiveis": 2}  # fmt: skip


def test_catalogos(client):
    c = client.get(f"{BASE}/catalogos").json()
    assert {"valor": "casaCondominio", "rotulo": "Casa de condomínio"} in c["tiposImovel"]
    assert "Piscina" in c["comodidadesPadrao"]
    assert "RJ" in c["estados"]

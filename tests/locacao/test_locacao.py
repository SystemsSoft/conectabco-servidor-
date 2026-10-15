from tests.apoio import contato, imovel, novo_id

BASE = "/api/v1/locacao"


def _contrato(client, **extra):
    dono = contato(client, "Dono")
    return {
        "imovelId": imovel(client, finalidades=["locacao"]),
        "locatarioId": contato(client, "Inquilino"),
        "beneficiarios": [{"contatoId": dono, "percentual": 100}],
        "dataInicio": "2026-01-01",
        "valorAluguel": 3000,
        "diaVencimento": 10,
        **extra,
    }


def test_contrato_numerado_e_atualizado(client):
    id1, id2 = novo_id(), novo_id()
    r = client.put(f"{BASE}/contratos/{id1}", json=_contrato(client))
    assert r.status_code == 201
    assert r.json()["numero"] == "LOC-0001"
    assert r.json()["beneficiarios"][0]["percentual"] == 100
    assert client.put(f"{BASE}/contratos/{id2}", json=_contrato(client)).json()[
        "numero"
    ] == "LOC-0002"
    dados = _contrato(client, valorAluguel=3500)
    r = client.put(f"{BASE}/contratos/{id1}", json=dados)
    assert (r.status_code, r.json()["numero"], r.json()["valorAluguel"]) == (
        200, "LOC-0001", 3500,
    )  # fmt: skip


def test_regras_do_contrato(client):
    dados = _contrato(client)
    dados["beneficiarios"][0]["percentual"] = 60
    r = client.put(f"{BASE}/contratos/{novo_id()}", json=dados)
    assert r.json()["detail"] == (
        "Os percentuais dos beneficiários somam 60.00%; devem somar 100%."
    )
    dados = _contrato(client)
    dados["beneficiarios"] = [{"contatoId": dados["locatarioId"], "percentual": 100}]
    r = client.put(f"{BASE}/contratos/{novo_id()}", json=dados)
    assert r.json()["detail"] == "O locatário não pode ser beneficiário do próprio contrato."


def test_despesa_cobranca_repasse_e_exclusao_em_cascata(client):
    cid = novo_id()
    dados = _contrato(client)
    client.put(f"{BASE}/contratos/{cid}", json=dados)
    dono = dados["beneficiarios"][0]["contatoId"]

    did = novo_id()
    r = client.put(f"{BASE}/despesas/{did}", json={
        "contratoId": cid, "descricao": "IPTU", "valor": 150,
        "responsavel": "proprietario", "competenciaInicio": "2026-01-01",
        "dedutivelIr": True,
    })  # fmt: skip
    assert r.status_code == 201 and r.json()["dedutivelIr"] is True

    bid = novo_id()
    cobranca = {
        "contratoId": cid, "competencia": "2026-02-01", "vencimento": "2026-02-10",
        "itens": [{"descricao": "Aluguel 02/2026", "valor": 3000, "tipo": "aluguel"}],
    }  # fmt: skip
    assert client.put(f"{BASE}/cobrancas/{bid}", json=cobranca).status_code == 201
    paga = cobranca | {"status": "paga", "dataPagamento": "2026-02-15",
                       "valorPago": 3330.5, "multa": 300, "juros": 30.5}  # fmt: skip
    r = client.put(f"{BASE}/cobrancas/{bid}", json=paga).json()
    assert (r["status"], r["valorPago"], r["itens"][0]["tipo"]) == ("paga", 3330.5, "aluguel")

    # Só uma cobrança por contrato e competência.
    r = client.put(f"{BASE}/cobrancas/{novo_id()}", json=cobranca)
    assert r.json()["detail"] == "Já existe cobrança deste contrato na competência."

    r = client.put(f"{BASE}/repasses/{bid}/{dono}", json={"data": "2026-02-20"})
    assert r.json() == {"cobrancaId": bid, "contatoId": dono, "data": "2026-02-20"}
    assert len(client.get(f"{BASE}/repasses").json()) == 1

    # Imóvel e locatário em contrato não podem ser excluídos.
    r = client.delete(f"/api/v1/crm/imoveis/{dados['imovelId']}")
    assert r.status_code == 409
    r = client.delete(f"/api/v1/crm/contatos/{dados['locatarioId']}")
    assert r.status_code == 409

    assert client.delete(f"{BASE}/contratos/{cid}").status_code == 204
    assert client.get(f"{BASE}/despesas").json()["total"] == 0
    assert client.get(f"{BASE}/cobrancas").json()["total"] == 0
    assert client.get(f"{BASE}/repasses").json() == []


def test_desmarcar_repasse(client):
    cid = novo_id()
    dados = _contrato(client)
    client.put(f"{BASE}/contratos/{cid}", json=dados)
    bid = novo_id()
    client.put(f"{BASE}/cobrancas/{bid}", json={
        "contratoId": cid, "competencia": "2026-03-15", "vencimento": "2026-03-10",
        "itens": [{"descricao": "Aluguel", "valor": 3000}],
    })  # fmt: skip
    assert client.get(f"{BASE}/cobrancas/{bid}").json()["competencia"] == "2026-03-01"
    dono = dados["beneficiarios"][0]["contatoId"]
    client.put(f"{BASE}/repasses/{bid}/{dono}", json={"data": "2026-03-20"})
    assert client.delete(f"{BASE}/repasses/{bid}/{dono}").status_code == 204
    assert client.get(f"{BASE}/repasses").json() == []

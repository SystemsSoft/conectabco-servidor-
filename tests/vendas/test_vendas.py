from tests.apoio import contato, imovel, novo_id

URL = "/api/v1/vendas"


def _venda(client, **extra):
    vendedor = contato(client, "Vendedor")
    corretor = contato(client, "Corretor")
    return {
        "imovelId": imovel(client),
        "compradores": [contato(client, "Comprador")],
        "vendedores": [{"contatoId": vendedor, "percentual": 100}],
        "dataVenda": "2026-10-01",
        "valorVenda": 500000,
        "valorEntrada": 100000,
        "vencimentoEntrada": "2026-10-05",
        "formaPagamento": "financiamentoProprio",
        "plano": {"numeroParcelas": 2, "taxaJurosMes": 1, "sistema": "price",
                  "primeiroVencimento": "2026-11-10"},
        "comissaoPercentual": 6,
        "corretores": [{"percentual": 50}, {"contatoId": corretor, "percentual": 50}],
        **extra,
    }  # fmt: skip


def _parcela(venda_id, numero=1, **extra):
    return {
        "id": novo_id(), "vendaId": venda_id, "numero": numero, "totalParcelas": 2,
        "tipo": "mensal", "vencimento": f"2026-{10 + numero}-10", "valor": 203000,
        "amortizacao": 199000, "juros": 4000, "saldoDevedor": 201000, **extra,
    }  # fmt: skip


def test_venda_numerada_com_plano_e_participacoes(client):
    id = novo_id()
    r = client.put(f"{URL}/{id}", json=_venda(client))
    assert r.status_code == 201
    v = r.json()
    assert v["numero"] == "VEN-0001"
    assert v["plano"]["sistema"] == "price"
    assert v["corretores"][0] == {"contatoId": None, "percentual": 50, "pagaEm": None}
    assert len(v["vendedores"]) == 1

    # Marcar comissão paga (PUT com pagaEm) mantém o número.
    dados = _venda(client)
    dados["corretores"][0]["pagaEm"] = "2026-10-10"
    r = client.put(f"{URL}/{id}", json=dados).json()
    assert (r["numero"], r["corretores"][0]["pagaEm"]) == ("VEN-0001", "2026-10-10")


def test_regras(client):
    dados = _venda(client)
    dados["vendedores"] = [{"contatoId": dados["compradores"][0], "percentual": 100}]
    r = client.put(f"{URL}/{novo_id()}", json=dados)
    assert r.json()["detail"] == "Uma pessoa não pode ser compradora e vendedora."
    r = client.put(f"{URL}/{novo_id()}", json=_venda(client, plano=None))
    assert r.json()["detail"] == "Informe a quantidade de parcelas."


def test_parcelas_em_lote_pagamento_e_bloqueio(client):
    vid = novo_id()
    dados = _venda(client)
    client.put(f"{URL}/{vid}", json=dados)
    lote = [_parcela(vid, 1), _parcela(vid, 2)]
    r = client.put(f"{URL}/parcelas", json=lote)
    assert r.status_code == 200 and len(r.json()) == 2
    assert client.get(f"{URL}/parcelas", params={"vendaId": vid}).json()["total"] == 2

    paga = lote[0] | {"status": "paga", "dataPagamento": "2026-11-12",
                      "valorPago": 207200, "multa": 4060, "jurosMora": 140}  # fmt: skip
    pid = paga.pop("id")
    r = client.put(f"{URL}/parcelas/{pid}", json=paga).json()
    assert (r["status"], r["jurosMora"]) == ("paga", 140)

    # Com parcela paga, não muda as condições de pagamento.
    r = client.put(f"{URL}/{vid}", json=dados | {"valorVenda": 600000})
    assert r.json()["detail"] == (
        "Há parcelas pagas: as condições de pagamento não podem ser alteradas."
    )
    # Mas outras alterações passam.
    assert client.put(f"{URL}/{vid}", json=dados | {"observacoes": "ok"}).status_code == 200

    # Imóvel vendido não pode ser excluído.
    assert client.delete(f"/api/v1/crm/imoveis/{dados['imovelId']}").status_code == 409

    assert client.delete(f"{URL}/{vid}/parcelas").status_code == 204
    assert client.get(f"{URL}/parcelas").json()["total"] == 0
    client.put(f"{URL}/parcelas", json=[_parcela(vid)])
    assert client.delete(f"{URL}/{vid}").status_code == 204
    assert client.get(f"{URL}/parcelas").json()["total"] == 0

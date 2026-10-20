from tests.apoio import contato, novo_id

URL = "/api/v1/financeiro"


def _conta(client, nome="Itaú Empresa") -> str:
    id = novo_id()
    r = client.put(f"{URL}/contas-bancarias/{id}", json={"nome": nome, "banco": "341"})
    assert r.status_code == 201
    return id


def test_conta_bancaria_guarda_o_link_do_banco(client):
    id = novo_id()
    link = "https://www.itau.com.br/empresas"
    r = client.put(f"{URL}/contas-bancarias/{id}", json={"nome": "Itaú", "linkInternetBanking": link})
    assert r.status_code == 201
    assert r.json()["linkInternetBanking"] == link
    assert client.put(f"{URL}/contas-bancarias/{id}", json={"nome": "Itaú"}).json()["linkInternetBanking"] == ""
    erro = client.put(f"{URL}/contas-bancarias/{id}", json={"nome": "Itaú", "linkInternetBanking": "http://x.com"})
    assert erro.status_code == 422


def _lanc(**extra):
    return {"tipo": "receber", "descricao": "Comissão", "valor": 5000,
            "vencimento": "2026-10-10", **extra}  # fmt: skip


def test_lancamento_lote_baixa_e_estorno(client):
    cliente = contato(client, "Cliente")
    lote = [{"id": novo_id(), **_lanc(contatoId=cliente, parcelaNumero=i,
                                       parcelaTotal=3, vencimento=f"2026-1{i - 1}-10")}
            for i in (1, 2, 3)]  # fmt: skip
    r = client.put(f"{URL}/lancamentos", json=lote)
    assert r.status_code == 200 and len(r.json()) == 3
    assert client.get(f"{URL}/lancamentos", params={"ate": "2026-10-31"}).json()["total"] == 1

    conta = _conta(client)
    id = lote[0]["id"]
    baixa = _lanc(status="baixado", dataBaixa="2026-10-12", valorBaixa=5110,
                  multa=100, juros=10, meio="pix", contaBaixaId=conta)  # fmt: skip
    r = client.put(f"{URL}/lancamentos/{id}", json=baixa).json()
    assert (r["status"], r["valorBaixa"], r["meio"]) == ("baixado", 5110, "pix")

    # Baixada não pode ser excluída; conta bancária usada também não.
    assert client.delete(f"{URL}/lancamentos/{id}").json()["detail"] == (
        "Estorne a baixa antes de excluir."
    )
    assert client.delete(f"{URL}/contas-bancarias/{conta}").json()["detail"] == (
        "A conta tem movimentações e não pode ser excluída."
    )

    # Conciliação: valor tem de bater com a baixa.
    linha = {"contaId": conta, "data": "2026-10-12", "descricao": "PIX recebido",
             "valor": 5110, "lancamentoId": id}  # fmt: skip
    errada = linha | {"valor": 5000}
    assert client.put(f"{URL}/extrato/{novo_id()}", json=errada).json()["detail"] == (
        "Os valores do extrato e da baixa são diferentes."
    )
    lid = novo_id()
    assert client.put(f"{URL}/extrato/{lid}", json=linha).status_code == 201
    assert client.put(f"{URL}/extrato/{novo_id()}", json=linha).json()["detail"] == (
        "Esta baixa já está conciliada com outra linha."
    )

    # Estorno bloqueado enquanto conciliada.
    r = client.put(f"{URL}/lancamentos/{id}", json=_lanc())
    assert r.json()["detail"].startswith("Esta baixa está conciliada")
    client.put(f"{URL}/extrato/{lid}", json=linha | {"lancamentoId": None})
    assert client.put(f"{URL}/lancamentos/{id}", json=_lanc()).json()["status"] == "aberto"


def test_boletos_com_nosso_numero_por_conta(client):
    conta1, conta2 = _conta(client), _conta(client, "Bradesco")
    l1, l2 = novo_id(), novo_id()
    client.put(f"{URL}/lancamentos/{l1}", json=_lanc())
    client.put(f"{URL}/lancamentos/{l2}", json=_lanc())

    def emitir(lanc, conta):
        return client.put(f"{URL}/boletos/{novo_id()}", json={
            "lancamentoId": lanc, "contaId": conta, "valor": 5000,
            "vencimento": "2026-10-10", "emissao": "2026-10-01",
        })  # fmt: skip

    b1 = emitir(l1, conta1).json()
    assert b1["nossoNumero"] == "0000000001"
    assert emitir(l1, conta1).json()["detail"] == (
        "Já existe um boleto em aberto para esta conta."
    )
    assert emitir(l2, conta1).json()["nossoNumero"] == "0000000002"
    assert emitir(l2, conta2).json()["detail"] == (
        "Já existe um boleto em aberto para esta conta."
    )

    pagar = client.put(f"{URL}/lancamentos/{novo_id()}", json=_lanc(tipo="pagar"))
    assert emitir(pagar.json()["id"], conta2).json()["detail"] == (
        "Só contas a receber geram boleto."
    )

    # Baixa pelo retorno: boleto pago mantém o nosso número.
    pago = {k: b1[k] for k in ("lancamentoId", "contaId", "nossoNumero", "valor",
                               "vencimento", "emissao")} | {
        "status": "pago", "dataPagamento": "2026-10-09", "valorPago": 5000}  # fmt: skip
    r = client.put(f"{URL}/boletos/{b1['id']}", json=pago).json()
    assert (r["status"], r["nossoNumero"]) == ("pago", "0000000001")

    # Conta com boleto emitido não pode ser excluída sem cancelar.
    assert client.delete(f"{URL}/lancamentos/{l2}").json()["detail"] == (
        "Cancele o boleto emitido antes de excluir a conta."
    )


def test_indices_e_configuracao(client):
    r = client.put(f"{URL}/indices", json={"indice": "igpm", "ano": 2026, "mes": 3,
                                          "percentual": 0.45})  # fmt: skip
    assert r.status_code == 200
    client.put(f"{URL}/indices", json={"indice": "igpm", "ano": 2026, "mes": 3, "percentual": 0.5})
    assert client.get(f"{URL}/indices").json() == [
        {"indice": "igpm", "ano": 2026, "mes": 3, "percentual": 0.5}
    ]
    assert client.put(f"{URL}/indices", json={"indice": "nenhum", "ano": 2026, "mes": 3,
                                             "percentual": 1}).json()["detail"] == "Selecione o índice."  # fmt: skip
    assert client.delete(f"{URL}/indices/igpm/2026/3").status_code == 204
    assert client.get(f"{URL}/indices").json() == []

    assert client.get(f"{URL}/configuracao").json()["multaPercentual"] == 2
    r = client.put(f"{URL}/configuracao", json={"multaPercentual": 10, "jurosMesPercentual": 1,
                                                "indicePadrao": "ipca"})  # fmt: skip
    assert client.get(f"{URL}/configuracao").json() == {
        "multaPercentual": 10, "jurosMesPercentual": 1, "indicePadrao": "ipca"}

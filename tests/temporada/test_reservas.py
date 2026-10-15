from tests.apoio import contato, imovel, novo_id

URL = "/api/v1/temporada"


def _reserva(imovel_id, hospede_id, check_in, check_out, **extra):
    return {
        "imovelId": imovel_id, "hospedeId": hospede_id, "checkIn": check_in,
        "checkOut": check_out, "hospedes": 2, "valorDiaria": 450,
        "taxaLimpeza": 150, **extra,
    }  # fmt: skip


def test_reserva_numerada_com_totais(client):
    im, h = imovel(client, finalidades=["temporada"]), contato(client, "Hóspede")
    r = client.put(f"{URL}/reservas/{novo_id()}",
                   json=_reserva(im, h, "2026-12-20", "2026-12-27", valorPago=1000))  # fmt: skip
    assert r.status_code == 201
    j = r.json()
    assert (j["numero"], j["noites"], j["total"], j["saldo"]) == ("RES-0001", 7, 3300, 2300)


def test_impede_sobreposicao_mas_permite_virada_no_mesmo_dia(client):
    im, h = imovel(client), contato(client, "Hóspede")
    client.put(f"{URL}/reservas/{novo_id()}", json=_reserva(im, h, "2026-12-20", "2026-12-27"))
    # Entra no dia em que o outro sai: ok.
    r = client.put(f"{URL}/reservas/{novo_id()}", json=_reserva(im, h, "2026-12-27", "2026-12-30"))
    assert r.status_code == 201
    # Sobrepõe: recusado com a reserva em conflito.
    r = client.put(f"{URL}/reservas/{novo_id()}", json=_reserva(im, h, "2026-12-25", "2026-12-28"))
    assert r.json()["detail"] == (
        "Período indisponível: conflita com a reserva RES-0001 (20/12/2026 a 27/12/2026)."
    )
    # Outro imóvel no mesmo período: ok.
    outro = imovel(client)
    r = client.put(f"{URL}/reservas/{novo_id()}", json=_reserva(outro, h, "2026-12-25", "2026-12-28"))
    assert r.status_code == 201


def test_bloqueio_cancelamento_e_disponibilidade(client):
    im, h = imovel(client), contato(client, "Hóspede")
    bid = novo_id()
    client.put(f"{URL}/reservas/{bid}", json={
        "imovelId": im, "bloqueio": True, "motivoBloqueio": "Pintura",
        "checkIn": "2027-01-05", "checkOut": "2027-01-10",
    })  # fmt: skip
    conflito = client.get(f"{URL}/disponibilidade", params={
        "imovelId": im, "checkIn": "2027-01-08", "checkOut": "2027-01-12"})  # fmt: skip
    assert [c["motivoBloqueio"] for c in conflito.json()] == ["Pintura"]

    r = client.put(f"{URL}/reservas/{novo_id()}", json=_reserva(im, h, "2027-01-08", "2027-01-12"))
    assert r.json()["detail"].startswith("Período indisponível: conflita com um bloqueio")

    # Cancelado deixa de ocupar o calendário.
    client.put(f"{URL}/reservas/{bid}", json={
        "imovelId": im, "bloqueio": True, "checkIn": "2027-01-05",
        "checkOut": "2027-01-10", "situacao": "cancelada",
    })  # fmt: skip
    r = client.put(f"{URL}/reservas/{novo_id()}", json=_reserva(im, h, "2027-01-08", "2027-01-12"))
    assert r.status_code == 201
    assert client.get(f"{URL}/reservas", params={"de": "2027-01-11"}).json()["total"] == 1


def test_validacoes(client):
    im, h = imovel(client), contato(client, "Hóspede")
    r = client.put(f"{URL}/reservas/{novo_id()}", json=_reserva(im, h, "2026-12-20", "2026-12-20"))
    assert r.json()["detail"] == "O check-out deve ser depois do check-in."
    r = client.put(f"{URL}/reservas/{novo_id()}", json=_reserva(im, None, "2026-12-20", "2026-12-22"))
    assert r.json()["detail"] == "Selecione o hóspede."
    r = client.put(f"{URL}/reservas/{novo_id()}",
                   json=_reserva(im, h, "2026-12-20", "2026-12-22", valorPago=5000))  # fmt: skip
    assert r.json()["detail"] == "O valor pago é maior que o total da reserva."

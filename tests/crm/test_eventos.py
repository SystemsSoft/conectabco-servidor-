from datetime import datetime, timedelta

URL = "/api/v1/crm/eventos"


def test_crud_e_alternar_conclusao(client):
    r = client.post(URL, json={"titulo": "Ligar para Ana", "tipo": "ligacao",
                               "dataHora": "2026-10-20T09:30:00", "prioridade": "alta"})  # fmt: skip
    assert r.status_code == 201
    e = r.json()
    assert e["dataHora"] == "2026-10-20T09:30:00"
    assert client.post(f"{URL}/{e['id']}/alternar-conclusao").json()["concluido"]
    assert client.delete(f"{URL}/{e['id']}").status_code == 204


def test_data_obrigatoria_exceto_anotacao(client):
    r = client.post(URL, json={"titulo": "Lembrete", "tipo": "lembrete"})
    assert r.json()["detail"] == "Informe a data e hora."
    assert client.post(URL, json={"titulo": "Nota", "tipo": "anotacao"}).status_code == 201


def test_pendentes_atrasados_ou_de_hoje(client):
    agora = datetime.now()
    def criar(titulo, quando, concluido=False):
        client.post(URL, json={"titulo": titulo, "dataHora": quando.isoformat(),
                               "concluido": concluido})  # fmt: skip

    criar("Ontem", agora - timedelta(days=1))
    criar("Hoje", agora.replace(hour=23, minute=0))
    criar("Amanhã", agora + timedelta(days=1, hours=1))
    criar("Feito", agora - timedelta(days=2), concluido=True)
    titulos = [e["titulo"] for e in client.get(f"{URL}/pendentes").json()]
    assert titulos == ["Ontem", "Hoje"]


def test_lista_em_ordem_cronologica_com_filtros(client):
    client.post(URL, json={"titulo": "Nota", "tipo": "anotacao"})
    client.post(URL, json={"titulo": "B", "dataHora": "2026-10-21T10:00:00"})
    client.post(URL, json={"titulo": "A", "dataHora": "2026-10-20T10:00:00"})
    titulos = [e["titulo"] for e in client.get(URL).json()["itens"]]
    assert titulos == ["A", "B", "Nota"]
    r = client.get(URL, params={"de": "2026-10-21T00:00:00"}).json()
    assert [e["titulo"] for e in r["itens"]] == ["B"]

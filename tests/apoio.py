"""Cadastros de apoio usados por vários testes."""

import uuid


def novo_id() -> str:
    return str(uuid.uuid4())


def contato(client, nome="Contato", **extra) -> str:
    id = novo_id()
    r = client.put(f"/api/v1/crm/contatos/{id}", json={"nome": nome, **extra})
    assert r.status_code == 201, r.text
    return id


def imovel(client, titulo="Imóvel", **extra) -> str:
    id = novo_id()
    r = client.put(f"/api/v1/crm/imoveis/{id}", json={"titulo": titulo, **extra})
    assert r.status_code == 201, r.text
    return id

from app.core.documentos import validar_cnpj, validar_cpf

URL = "/api/v1/fiscal/declarante"


def test_validacao_de_documentos():
    assert validar_cpf("529.982.247-25")
    assert not validar_cpf("529.982.247-24")
    assert not validar_cpf("111.111.111-11")
    assert validar_cnpj("11.222.333/0001-81")
    assert not validar_cnpj("11.222.333/0001-82")


def test_declarante_padrao_salvar_e_validar(client):
    assert client.get(URL).json()["nome"] == "Imobiliária Teste"  # nome do cadastro
    dados = {"documento": "11.222.333/0001-81", "nome": "Marcelo Bonifácio Imóveis",
             "responsavelNome": "Marcelo Bonifácio", "responsavelCpf": "529.982.247-25",
             "retificadora": True, "numeroRecibo": "12.34.56.78.90-12"}  # fmt: skip
    assert client.put(URL, json=dados).json() == dados
    assert client.get(URL).json() == dados

    r = client.put(URL, json=dados | {"documento": "11.222.333/0001-82"})
    assert r.json()["detail"] == "CNPJ/CPF do declarante inválido."
    r = client.put(URL, json=dados | {"responsavelCpf": "111.111.111-11"})
    assert r.json()["detail"] == "CPF do responsável inválido."
    assert client.put(URL, json=dados | {"nome": " "}).json()["detail"] == (
        "Informe o nome do declarante."
    )

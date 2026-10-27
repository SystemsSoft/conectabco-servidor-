"""Dados do contratante (contrato de prestação de serviços) no cadastro da
imobiliária: obrigatórios na criação, conferidos e editáveis depois."""

import pytest

from app.central import contratante as ct
from app.central import services as central
from app.core import imobiliarias
from app.core.errors import RegraNegocio
from tests.central.test_painel import CONTRATO, _entrar, _nova, painel  # noqa: F401 - fixture


def _dados(**extra) -> ct.DadosContrato:
    return ct.DadosContrato(**{k.removeprefix("contrato_"): v for k, v in CONTRATO.items()} | extra)


@pytest.mark.parametrize(("extra", "erro"), [
    ({"nome": ""}, "informe o nome"),
    ({"uf": "XX"}, "escolha o estado"),
    ({"cpf": "", "cnpj": ""}, "CPF ou o CNPJ"),
    ({"cpf": "111.111.111-11"}, "CPF inválido"),
    ({"cpf": "", "cnpj": "11.111.111/1111-11"}, "CNPJ inválido"),
    ({"identidade": ""}, "identidade"),
    ({"creci": "", "creci_pj": ""}, "CRECI ou o CRECI PJ"),
    ({"telefone_1": "1234"}, "telefone inválido"),
    ({"horario_implantacao": "25:00"}, "horário"),
    ({"data_implantacao": "31/10/2026"}, "Data da implantação inválida"),
])  # fmt: skip
def test_validacoes(extra, erro):
    with pytest.raises(RegraNegocio, match=erro):
        ct.validar(_dados(**extra))


def test_pessoa_juridica_sem_cpf_e_sem_identidade():
    v = ct.validar(_dados(cpf="", identidade="", creci="", cnpj="11.444.777/0001-61", creci_pj="J-1234 RJ",
                          data_implantacao="2026-11-03", horario_implantacao="14:30"))  # fmt: skip
    assert (v["cnpj"], v["creci_pj"], v["uf"]) == ("11444777000161", "J-1234 RJ", "RJ")
    assert v["data_implantacao"].isoformat() == "2026-11-03" and v["horario_implantacao"] == "14:30"


def test_criacao_exige_e_grava_o_contratante(painel):  # noqa: F811
    csrf = _entrar(painel)
    sem_contrato = {k: "" for k in CONTRATO}
    r = _nova(painel, csrf, **sem_contrato)
    assert r.status_code == 422 and "Contrato: informe o nome do contratante." in r.text
    imobiliarias.limpar_cadastro()
    assert imobiliarias.buscar("joao") is None  # nada foi criado

    r = _nova(painel, csrf, contrato_instagram="@joaoimoveis", contrato_data_implantacao="2026-11-03",
              contrato_horario_implantacao="09:00", contrato_dns="Registro.br")  # fmt: skip
    assert r.headers["location"] == "/plataforma/joao?msg=criada"
    with central.sessao() as db:
        salvo = ct.obter(db, "joao")
        assert (salvo.nome, salvo.cpf, salvo.instagram, salvo.dns) == (
            "João da Silva", "52998224725", "@joaoimoveis", "Registro.br")
        assert salvo.data_implantacao.isoformat() == "2026-11-03" and salvo.horario_implantacao == "09:00"
    pagina = painel.get("/plataforma/joao").text
    assert 'name="contrato_instagram" value="@joaoimoveis"' in pagina
    assert "ainda não preenchidos" not in pagina


def test_editar_o_contratante_na_pagina_da_imobiliaria(painel):  # noqa: F811
    csrf = _entrar(painel)
    _nova(painel, csrf)
    with central.sessao() as db:  # imobiliária de antes do contrato: sem os dados
        db.delete(ct.obter(db, "joao"))
        db.commit()
    assert "ainda não preenchidos" in painel.get("/plataforma/joao").text

    url = "/plataforma/joao/contrato"
    assert painel.post(url, data=CONTRATO).status_code == 403
    r = painel.post(url, data={"csrf": csrf} | CONTRATO | {"contrato_cpf": "123"})
    assert "CPF%20inv%C3%A1lido" in r.headers["location"]
    r = painel.post(url, data={"csrf": csrf} | CONTRATO | {"contrato_telefone_2": "(21) 3333-4444"})
    assert r.headers["location"] == "/plataforma/joao?msg=contrato"
    with central.sessao() as db:
        assert ct.obter(db, "joao").telefone_2 == "(21) 3333-4444"
    assert painel.post("/plataforma/nao-existe/contrato", data={"csrf": csrf} | CONTRATO).status_code == 404

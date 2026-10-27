"""Comercial: leads do pré-cadastro do site, funil das solicitações,
desempenho dos representantes e receita recorrente."""

from datetime import timedelta
from decimal import Decimal

import pytest

from app.central import comercial as com
from app.central import models as m
from app.central import pre_cadastro
from app.central import representantes as rep
from app.central import services as central
from app.core.config import get_settings
from app.core.tempo import agora
from tests.central.test_painel import _entrar, painel  # noqa: F401 - fixture
from tests.central.test_representantes import CORRETOR, _pagar

LEAD = {"nome": "Ana Prado", "email": "Ana@Exemplo.com", "whatsapp": "(24) 99999-1234", "creci": "",
        "cidade": "Barra do Piraí/RJ", "perfil": "Corretor autônomo", "sistema": "on", "lgpd": "on"}  # fmt: skip
URL = "/associacao/pre-cadastro"


@pytest.fixture(autouse=True)
def limpar_limite():
    pre_cadastro._envios.clear()


def test_pre_cadastro_do_site_vira_lead(painel, monkeypatch):  # noqa: F811
    r = painel.post(URL, data=LEAD | {"lgpd": ""})
    assert r.status_code == 422 and "LGPD" in r.json()["detail"]
    assert painel.post(URL, data=LEAD | {"perfil": "Outro"}).status_code == 422
    assert painel.post(URL, data=LEAD | {"empresa_site": "spam"}).status_code == 204  # robô: ignorado
    assert painel.post(URL, data=LEAD).status_code == 204
    with central.sessao() as db:
        (lead,) = com.leads(db, "todos")
        assert (lead.nome, lead.email, lead.quer_sistema, lead.situacao) == ("Ana Prado", "ana@exemplo.com", True, "novo")

    # Só o site institucional (Origin) e no máximo 5 por hora por IP.
    monkeypatch.setattr(get_settings(), "site_principal_url", "https://xn--associaoconectabci-7sb3f.com.br/")
    assert painel.post(URL, data=LEAD, headers={"Origin": "https://malicioso.com"}).status_code == 403
    site = {"Origin": "https://xn--associaoconectabci-7sb3f.com.br"}
    pre_cadastro._envios.clear()
    # O site lê o resultado (CORS só para ele) e mostra a mensagem de erro.
    r = painel.post(URL, data=LEAD | {"whatsapp": "123"}, headers=site)
    assert r.status_code == 422 and r.json()["detail"] == "WhatsApp inválido: informe o DDD e o número."
    assert r.headers["access-control-allow-origin"] == site["Origin"]
    r = painel.post(URL, data=LEAD, headers=site)
    assert r.status_code == 204 and r.headers["access-control-allow-origin"] == site["Origin"]
    pre_cadastro._envios.clear()
    estados = [painel.post(URL, data=LEAD, headers=site) for _ in range(6)]
    assert [r.status_code for r in estados] == [204] * 5 + [429] and "Tente de novo" in estados[-1].json()["detail"]


def test_lead_vira_solicitacao(painel):  # noqa: F811
    painel.post(URL, data=LEAD)
    csrf = _entrar(painel)
    pagina = painel.get("/plataforma/comercial/leads").text
    assert "Ana Prado" in pagina and "Quer conhecer o sistema" in pagina and "https://wa.me/5524999991234" in pagina
    menu = pagina.split('aria-label="Áreas da plataforma"')[1].split("</nav>")[0]
    assert '<summary>Comercial <span class="contador">1</span>' in menu
    lid = pagina.split('action="/plataforma/comercial/leads/')[1].split('"')[0]

    r = painel.post(f"/plataforma/comercial/leads/{lid}", data={"csrf": csrf, "situacao": "convertido"})
    assert "converter" in r.headers["location"]
    painel.post(f"/plataforma/comercial/leads/{lid}", data={"csrf": csrf, "situacao": "em_contato", "anotacao": "Ligar segunda"})
    assert "Ligar segunda" in painel.get("/plataforma/comercial/leads?situacao=em_contato").text

    form = painel.get(f"/plataforma/solicitacoes/nova?lead={lid}").text
    assert 'value="Ana Prado"' in form and 'value="Barra do Piraí"' in form and '<option value="RJ" selected>' in form
    assert f'name="lead" value="{lid}"' in form
    dados = CORRETOR | {"csrf": csrf, "lead": lid, "nome": "Ana Prado"}
    assert painel.post("/plataforma/solicitacoes/nova", data=dados).status_code == 303
    with central.sessao() as db:
        lead = com.lead(db, lid)
        assert lead.situacao == "convertido" and rep.solicitacao(db, lead.solicitacao_id).nome == "Ana Prado"
    assert "Virou solicitação" in painel.get("/plataforma/comercial/leads?situacao=convertido").text


def _solicitacao(db, autor, dias_atras: int, situacao: str = "nova", pago_dias: int | None = None,
                 implantada_dias: int | None = None) -> m.SolicitacaoImplantacao:  # fmt: skip
    s = rep.enviar_solicitacao(db, autor, rep.DadosCorretor(**{k: v for k, v in CORRETOR.items()}))
    momento = agora()
    s.criada_em = momento - timedelta(days=dias_atras)
    if pago_dias is not None:
        s.primeiro_pagamento_em = (momento - timedelta(days=pago_dias)).date()
        s.primeiro_pagamento_confirmado_em = momento - timedelta(days=pago_dias)
    s.situacao = situacao
    if implantada_dias is not None:
        s.implantada_em = momento - timedelta(days=implantada_dias)
    db.commit()
    return s


def test_funil_e_representantes(painel):  # noqa: F811
    with central.sessao() as db:
        carlos = rep.salvar_representante(db, None, "Carlos", "carlos", "c@x.com", "(21) 97777-6666", "Niterói", "senha-123456")
        bia = rep.salvar_representante(db, None, "Bia", "bia", "b@x.com", "(21) 96666-5555", "", "senha-123456")
        rep.salvar_representante(db, None, "Davi", "davi", "d@x.com", "(21) 95555-4444", "", "senha-123456")
        _solicitacao(db, carlos, 20, "implantada", pago_dias=16, implantada_dias=10)  # 4 dias + 6 dias
        _solicitacao(db, carlos, 12, "em_andamento", pago_dias=10)  # 2 dias
        _solicitacao(db, carlos, 5)
        _solicitacao(db, bia, 3, "recusada")
        _solicitacao(db, bia, 400, "implantada", pago_dias=399, implantada_dias=390)  # fora dos 12 meses e há 400 dias

        f = com.funil(db, com.inicio_do_periodo("12m"))
        assert (f.entradas, f.pagas, f.em_implantacao, f.implantadas, f.recusadas, f.aguardando) == (4, 2, 2, 1, 1, 1)
        assert [e["taxa"] for e in f.etapas] == [None, 50, 100, 50]
        assert (f.dias_ate_pagamento, f.dias_ate_implantacao, f.dias_total) == (3.0, 6.0, 10.0)
        assert com.funil(db, None).entradas == 5

        d = {x.nome: x for x in com.desempenho(db, com.inicio_do_periodo("12m"))}
        assert (d["Carlos"].enviadas, d["Carlos"].implantadas, d["Carlos"].conversao) == (3, 1, 33)
        assert (d["Bia"].enviadas, d["Bia"].recusadas) == (1, 1)
        assert [x.nome for x in com.desempenho(db, None)][:2] == ["Carlos", "Bia"]  # empate em implantadas: mais enviadas
        assert sorted(r.nome for r, _ in com.sem_envio(db)) == ["Davi"]

    _entrar(painel)
    pagina = painel.get("/plataforma/comercial?periodo=12m").text
    assert "Funil de implantação" in pagina and "3,0 dias" in pagina and "6,0 dias" in pagina
    pagina = painel.get("/plataforma/comercial/representantes?periodo=tudo").text
    assert "Carlos" in pagina and "33%" in pagina and "Davi" in pagina and "nunca enviou" in pagina


def test_receita_e_plano(painel):  # noqa: F811
    from tests.central.test_painel import _nova

    csrf = _entrar(painel)
    r = _nova(painel, csrf, mensalidade="abc")
    assert r.status_code == 422 and "Mensalidade inválida" in r.text
    assert _nova(painel, csrf, mensalidade="199,90", dia_vencimento="10").headers["location"] == "/plataforma/joao?msg=criada"
    pagina = painel.get("/plataforma/joao").text
    assert 'name="mensalidade" value="199,90"' in pagina and 'name="dia_vencimento" value="10"' in pagina
    assert "Dia%20do%20vencimento" in painel.post("/plataforma/joao/plano",
                                                  data={"csrf": csrf, "mensalidade": "150", "dia_vencimento": "31"}).headers["location"]  # fmt: skip
    painel.post("/plataforma/joao/plano", data={"csrf": csrf, "mensalidade": "150,00", "dia_vencimento": "5"})

    with central.sessao() as db:
        momento = agora()
        db.add_all([
            m.Imobiliaria(slug="antiga", nome="Antiga", banco="imob_antiga", site_url="", ativa=True, cor_primaria="",
                          cor_destaque="", criada_em=momento - timedelta(days=200), mensalidade=Decimal("100.00")),
            m.Imobiliaria(slug="saiu", nome="Saiu", banco="imob_saiu", site_url="", ativa=True, cor_primaria="",
                          cor_destaque="", criada_em=momento - timedelta(days=300), mensalidade=Decimal("150.00")),
        ])  # fmt: skip
        db.commit()
        central.definir_ativa(db, "saiu", False)
        r = com.receita(db)
        assert (r.ativas, r.receita, r.ticket) == (2, Decimal("250.00"), Decimal("125.00"))
        assert (r.novas_no_mes, r.canceladas_no_mes) == (1, 1)
        assert r.meses[-2].receita == Decimal("250.00")  # mês passado: antiga + saiu
        central.definir_ativa(db, "saiu", True)
        assert com.receita(db).canceladas_no_mes == 0  # reativada: deixa de contar

    pagina = painel.get("/plataforma/comercial/receita").text
    assert "Receita recorrente" in pagina and "R$ 400,00" in pagina and "ticket médio" in pagina


def test_periodo():
    from datetime import date, datetime

    hoje = date(2026, 3, 15)
    assert com.inicio_do_periodo("mes", hoje) == datetime(2026, 3, 1)
    assert com.inicio_do_periodo("3m", hoje) == datetime(2026, 1, 1)
    assert com.inicio_do_periodo("12m", hoje) == datetime(2025, 4, 1)
    assert com.inicio_do_periodo("tudo", hoje) is None
    assert com.validar_plano("R$ 1.234,56", "28") == (Decimal("1234.56"), 28)

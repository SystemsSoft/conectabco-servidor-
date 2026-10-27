"""Área do representante e, no painel, as solicitações de implantação e o
cadastro dos representantes."""

from app.central import services as central
from tests.central.test_painel import CONTRATO, PNG, _csrf, _entrar, painel  # noqa: F401 - fixture

REP = {"login": "carlos.rep", "senha": "senha-do-carlos"}
CORRETOR = {
    "nome": "Joana Lima", "cpf_cnpj": "529.982.247-25", "creci": "12345-F RJ",
    "email": "joana@limaimoveis.com.br", "telefone": "(21) 98888-7777",
    "nome_imobiliaria": "Lima Imóveis", "cidade": "Niterói", "uf": "RJ",
    "dominio": "https://limaimoveis.com.br/", "imoveis": "120", "contratos": "45", "usuarios": "3",
    "observacoes": "Usa planilha hoje.",
}  # fmt: skip


def _cadastrar_representante(c, csrf, **extra):
    dados = {"csrf": csrf, "nome": "Carlos Souza", "email": "carlos@exemplo.com",
             "telefone": "(21) 97777-6666", "regiao": "Niterói"} | REP | extra  # fmt: skip
    return c.post("/plataforma/representantes", data=dados)


def _pagar(c, csrf, sid):
    from datetime import date

    r = c.post(f"/plataforma/financeiro/{sid}/pagamento", data={"csrf": csrf, "data_pagamento": date.today().isoformat()})
    assert r.headers["location"] == f"/plataforma/financeiro/{sid}?msg=pagamento", r.headers["location"]


def _entrar_representante(c, **dados) -> str:
    r = c.post("/representante/entrar", data=REP | dados)
    assert r.status_code == 303, r.text
    return _csrf(c.get("/representante").text)


def test_fluxo_do_representante_ate_a_implantacao(painel):  # noqa: F811
    csrf = _entrar(painel)
    r = _cadastrar_representante(painel, csrf, email="sem-arroba")
    assert r.status_code == 422 and "E-mail inválido." in r.text
    assert _cadastrar_representante(painel, csrf).headers["location"].endswith("msg=representante-criado")
    assert "já existe" in _cadastrar_representante(painel, csrf).text.lower()
    lista = painel.get("/plataforma/representantes").text
    assert "Carlos Souza" in lista and "carlos.rep" in lista

    # O login do painel não abre a área do representante (e vice-versa).
    assert painel.get("/representante").headers["location"] == "/representante/entrar"
    assert painel.post("/representante/entrar", data=REP | {"senha": "errada"}).status_code == 422
    csrf_rep = _entrar_representante(painel)
    painel.cookies.delete("plataforma", path="/plataforma")
    assert painel.get("/plataforma").headers["location"] == "/plataforma/entrar"

    # Envio do corretor (com CSRF e dados conferidos).
    assert painel.post("/representante/novo", data=CORRETOR).status_code == 403
    r = painel.post("/representante/novo", data=CORRETOR | {"csrf": csrf_rep, "cpf_cnpj": "111.111.111-11"})
    assert r.status_code == 422 and "CPF ou CNPJ inválido." in r.text and "Joana Lima" in r.text
    r = painel.post("/representante/novo", data=CORRETOR | {"csrf": csrf_rep})
    assert r.headers["location"] == "/representante?msg=enviada"
    inicio = painel.get("/representante").text
    assert "Joana Lima" in inicio and "Lima Imóveis" in inicio and ">Nova<" in inicio

    # No painel: aba com o contador, dados do corretor e contato do representante.
    csrf = _entrar(painel)
    pagina = painel.get("/plataforma/solicitacoes").text
    assert 'class="contador">1<' in pagina
    for texto in ("Lima Imóveis", "529.982.247-25", "CRECI 12345-F RJ", "limaimoveis.com.br",
                  "Carlos Souza", "carlos@exemplo.com", "https://wa.me/5521977776666", "45 contratos"):
        assert texto in pagina, texto
    sid = pagina.split('action="/plataforma/solicitacoes/')[1].split('"')[0]

    # Sem o 1º pagamento confirmado pelo financeiro, a Tecnologia não avança nem implanta.
    andamento = {"csrf": csrf, "situacao": "em_andamento", "resposta": "Apresentação marcada para 28/10."}
    r = painel.post(f"/plataforma/solicitacoes/{sid}", data=andamento)
    assert "financeiro%20ainda%20n%C3%A3o%20confirmou" in r.headers["location"]
    assert "falta o 1º pagamento" in pagina and f"/plataforma/nova?solicitacao={sid}" not in pagina
    assert "financeiro" in painel.get(f"/plataforma/nova?solicitacao={sid}").headers["location"].lower()
    _pagar(painel, csrf, sid)
    painel.post(f"/plataforma/solicitacoes/{sid}", data=andamento)
    _entrar_representante(painel)
    inicio = painel.get("/representante").text
    assert "Em implantação" in inicio and "Apresentação marcada para 28/10." in inicio

    # Implantar: o cadastro da imobiliária já vem preenchido e fecha a solicitação.
    csrf = _entrar(painel)
    nova = painel.get(f"/plataforma/nova?solicitacao={sid}").text
    assert 'value="Lima Imóveis"' in nova and 'value="lima"' in nova and 'value="Joana Lima"' in nova
    # O contratante já vem da solicitação (CPF, CRECI, telefone, cidade/UF).
    for campo, valor in (("cpf", "529.982.247-25"), ("creci", "12345-F RJ"), ("telefone_1", "(21) 98888-7777"),
                         ("cidade", "Niterói"), ("nome_comercial", "Lima Imóveis")):
        assert f'name="contrato_{campo}" value="{valor}"' in nova, campo
    assert '<option value="RJ" selected>' in nova
    r = painel.post("/plataforma/nova", data={
        "csrf": csrf, "slug": "lima", "nome": "Lima Imóveis", "dominios": "limaimoveis.com.br",
        "admin_nome": "Joana Lima", "admin_login": "joana", "admin_senha": "senha-da-joana",
        "solicitacao": sid} | CONTRATO, files={"logo": ("logo.png", PNG, "image/png")})  # fmt: skip
    assert r.headers["location"] == "/plataforma/lima?msg=criada"
    implantadas = painel.get("/plataforma/solicitacoes?situacao=implantada").text
    assert "Lima Imóveis" in implantadas and 'href="/plataforma/lima"' in implantadas
    _entrar_representante(painel)
    assert "Implantada" in painel.get("/representante").text


def test_desativar_ou_trocar_a_senha_derruba_o_representante(painel):  # noqa: F811
    csrf = _entrar(painel)
    _cadastrar_representante(painel, csrf)
    rid = painel.get("/plataforma/representantes").text.split("/plataforma/representantes/")[1].split('"')[0]
    _entrar_representante(painel)
    assert painel.get("/representante").status_code == 200

    csrf = _entrar(painel)
    dados = {"csrf": csrf, "nome": "Carlos Souza", "login": REP["login"], "email": "carlos@exemplo.com",
             "telefone": "(21) 97777-6666", "regiao": ""}  # fmt: skip
    assert painel.post(f"/plataforma/representantes/{rid}", data=dados).status_code == 303  # ativo desmarcado
    assert painel.get("/representante").headers["location"] == "/representante/entrar"
    r = painel.post("/representante/entrar", data=REP)
    assert r.status_code == 422 and "desativado" in r.text

    painel.post(f"/plataforma/representantes/{rid}", data=dados | {"ativo": "1", "senha": "nova-senha-123"})
    assert painel.post("/representante/entrar", data=REP).status_code == 422
    _entrar_representante(painel, senha="nova-senha-123")


def test_caminhos_do_painel_nao_viram_imobiliaria(plataforma):
    import pytest

    from app.core.errors import RegraNegocio

    for slug in ("solicitacoes", "representantes"):
        with central.sessao() as db, pytest.raises(RegraNegocio, match="reservado"):
            central.validar_nova(db, slug, "X")


def test_menu_tecnologia_financeiro_e_comercial(painel):  # noqa: F811
    _entrar(painel)

    def menu(caminho):
        r = painel.get(caminho)
        assert r.status_code == 200, caminho
        return r.text.split('aria-label="Áreas da plataforma"')[1].split("</nav>")[0]

    m = menu("/plataforma")
    assert m.index("Tecnologia") < m.index("Financeiro") < m.index("Comercial")
    tecnologia, comercial = (bloco.split("</details>")[0] for bloco in m.split("<details")[1:3])
    for rotulo in ("Imobiliárias", "Solicitações", "Representantes", "Infraestrutura"):
        assert rotulo in tecnologia
    for rotulo in ("Funil", "Representantes", "Receita", "Leads do site"):
        assert rotulo in comercial
    assert m.count('class="grupo atual"') == 1 and 'class="grupo atual">\n          <summary>Tecnologia' in m
    m = menu("/plataforma/financeiro")
    assert 'href="/plataforma/financeiro" class="atual"' in m and 'class="grupo atual"' not in m
    for caminho in ("/plataforma/comercial", "/plataforma/comercial/representantes",
                    "/plataforma/comercial/receita", "/plataforma/comercial/leads"):
        m = menu(caminho)
        assert f'href="{caminho}" class="atual"' in m and "<summary>Comercial" in m.split('class="grupo atual">')[1][:60]
    # Representantes do Comercial não acende o de Tecnologia (e vice-versa).
    assert 'href="/plataforma/representantes" class="atual"' not in menu("/plataforma/comercial/representantes")
    assert 'class="atual">Solicitações' in menu("/plataforma/solicitacoes")

def test_nova_imobiliaria_pelo_fluxo_de_solicitacao(painel):  # noqa: F811
    csrf = _entrar(painel)
    # O botão saiu de Imobiliárias e foi para Solicitações.
    assert 'href="/plataforma/nova"' not in painel.get("/plataforma").text
    pagina = painel.get("/plataforma/solicitacoes").text
    assert 'href="/plataforma/solicitacoes/nova"' in pagina and "+ Nova imobiliária" in pagina

    form = painel.get("/plataforma/solicitacoes/nova").text
    assert 'name="cpf_cnpj"' in form and 'name="creci"' in form
    assert painel.post("/plataforma/solicitacoes/nova", data=CORRETOR).status_code == 403
    r = painel.post("/plataforma/solicitacoes/nova", data=CORRETOR | {"csrf": csrf, "uf": ""})
    assert r.status_code == 422 and "Escolha o estado" in r.text and "Joana Lima" in r.text
    r = painel.post("/plataforma/solicitacoes/nova", data=CORRETOR | {"csrf": csrf})
    assert r.headers["location"] == "/plataforma/solicitacoes?msg=solicitacao-criada"

    pagina = painel.get("/plataforma/solicitacoes").text
    assert "Lima Imóveis" in pagina and "Cadastrada no painel" in pagina and "Dona da Plataforma" in pagina
    assert 'class="contador">1<' in pagina
    sid = pagina.split('action="/plataforma/solicitacoes/')[1].split('"')[0]
    implantar = {"csrf": csrf, "slug": "lima", "nome": "Lima Imóveis", "admin_nome": "Joana Lima",
                 "admin_login": "joana", "admin_senha": "senha-da-joana", "solicitacao": sid} | CONTRATO  # fmt: skip
    r = painel.post("/plataforma/nova", data=implantar)  # sem o 1º pagamento: nada é criado
    assert r.status_code == 422 and "financeiro ainda não confirmou" in r.text
    assert painel.get("/plataforma/lima").status_code == 404
    _pagar(painel, csrf, sid)
    r = painel.post("/plataforma/nova", data=implantar)
    assert r.headers["location"] == "/plataforma/lima?msg=criada"
    implantadas = painel.get("/plataforma/solicitacoes?situacao=implantada").text
    assert "Lima Imóveis" in implantadas and 'href="/plataforma/lima"' in implantadas

from datetime import timedelta

import pytest

from app.core.config import get_settings
from app.core.tempo import agora
from app.modules.equipe.enums import PerfilAcesso, permissoes_do_perfil
from app.modules.site import services
from tests.apoio import novo_id

API = "/api/v1/site"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100


@pytest.fixture(autouse=True)
def isolar(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "arquivos_dir", str(tmp_path))
    services._envios.clear()


def _imovel(client, **extra) -> dict:
    dados = {
        "titulo": "Apartamento vista mar", "finalidades": ["venda", "locacao"],
        "tipo": "apartamento", "logradouro": "Rua Moreira César", "numero": "200",
        "complemento": "Apto 801", "bairro": "Icaraí", "cidade": "Niterói", "uf": "RJ",
        "valorVenda": 850000, "valorLocacao": 4500, "quartos": 3, "areaUtil": 110,
        "observacoesInternas": "SEGREDO-INTERNO", "matricula": "MAT-999",
        "publicarSite": True,
    } | extra  # fmt: skip
    r = client.put(f"/api/v1/crm/imoveis/{novo_id()}", json=dados)
    assert r.status_code in (200, 201), r.text
    return r.json()


def _corretor(client, login="carla", perfil="corretor") -> tuple[str, dict]:
    uid = novo_id()
    client.put(f"/api/v1/equipe/usuarios/{uid}", json={
        "nome": login.title(), "login": login, "perfil": perfil, "atendeNaFila": True,
        "permissoes": permissoes_do_perfil(PerfilAcesso(perfil)),
        "senha": "senha-forte-123"})  # fmt: skip
    r = client.post("/api/v1/auth/entrar", json={"usuario": login, "senha": "senha-forte-123"})
    return uid, {"Authorization": f"Bearer {r.json()['token']}"}


def _lead(client, **campos):
    dados = {"nome": "Ana Souza", "telefone": "(21) 98888-7777", "email": "ana@x.com",
             "mensagem": "Quero visitar", "consentimento": "on", "retorno": "/"} | campos  # fmt: skip
    return client.post("/enviar", data=dados, follow_redirects=False)


# ------------------------------------------------------------ Configuração


def test_configuracao_padrao_e_validacoes(client):
    cfg = client.get(f"{API}/configuracao").json()
    assert cfg["noAr"] is True and cfg["distribuirNaFila"] is True
    cfg |= {"titulo": "Seu novo lar", "whatsapp": "(21) 99999-0000"}
    salvo = client.put(f"{API}/configuracao", json=cfg).json()
    assert (salvo["titulo"], salvo["whatsapp"]) == ("Seu novo lar", "21999990000")
    erro = client.put(f"{API}/configuracao", json=cfg | {"instagram": "javascript:alert(1)"})
    assert erro.json()["detail"] == "Link do Instagram deve começar com https://"
    assert client.put(f"{API}/configuracao", json=cfg | {"whatsapp": "123"}).status_code == 422


# ----------------------------------------------------------------- Páginas


def test_site_mostra_so_publicados_sem_dados_internos(client):
    pub = _imovel(client, destaqueSite=True)
    _imovel(client, titulo="Casa oculta", publicarSite=False)
    _imovel(client, titulo="Já vendido", status="vendido")
    sem_endereco = _imovel(client, titulo="Endereço reservado", exibirEnderecoSite=False)

    home = client.get("/").text
    assert "Apartamento vista mar" in home and "Destaque" in home
    assert "Casa oculta" not in home and "Já vendido" not in home

    detalhe = client.get(f"/imovel/{pub['codigo']}").text
    assert "R$ 850.000" in detalhe and "R$ 4.500/mês" in detalhe
    assert "Rua Moreira César, 200" in detalhe
    for interno in ("SEGREDO-INTERNO", "MAT-999", "Apto 801"):
        assert interno not in detalhe
    reservado = client.get(f"/imovel/{sem_endereco['codigo']}").text
    assert "Rua Moreira César" not in reservado and "Icaraí" in reservado
    assert client.get("/imovel/IM-9999").status_code == 404

    lista = client.get("/imoveis?finalidade=locacao&preco_max=5000").text
    assert "Apartamento vista mar" in lista
    assert "Apartamento vista mar" not in client.get("/imoveis?preco_max=100000").text
    assert "Nenhum imóvel encontrado" in client.get("/imoveis?tipo=casa").text

    cfg = client.get(f"{API}/configuracao").json()
    client.put(f"{API}/configuracao", json=cfg | {"mostrarValores": False})
    assert "R$ 850.000" not in client.get(f"/imovel/{pub['codigo']}").text

    mapa = client.get("/sitemap.xml").text
    assert f"/imovel/{pub['codigo']}" in mapa and "Casa oculta" not in mapa
    assert "Sitemap:" in client.get("/robots.txt").text


def test_site_fora_do_ar(client):
    cfg = client.get(f"{API}/configuracao").json()
    client.put(f"{API}/configuracao", json=cfg | {"noAr": False})
    r = client.get("/")
    assert r.status_code == 503 and "Estamos preparando novidades" in r.text


def test_midia_so_de_imovel_publicado(client):
    def enviar(categoria="foto", nome="f.png", conteudo=PNG):
        return client.post("/api/v1/arquivos", data={"categoria": categoria},
                           files={"arquivo": (nome, conteudo)}).json()  # fmt: skip

    foto, oculta, doc = enviar(), enviar(), enviar("arquivo", "m.pdf", b"%PDF-1.4")
    pub = _imovel(client, anexos=[
        {"tipo": "foto", "titulo": "Sala", "url": foto["referencia"]},
        {"tipo": "arquivo", "titulo": "Matrícula", "url": doc["referencia"]},
        {"tipo": "link", "titulo": "Tour", "url": "https://youtu.be/dQw4w9WgXcQ"},
        {"tipo": "foto", "titulo": "XSS", "url": "javascript:alert(1)"}])  # fmt: skip
    _imovel(client, publicarSite=False, anexos=[
        {"tipo": "foto", "titulo": "x", "url": oculta["referencia"]}])  # fmt: skip

    assert client.get(f"/midia/{foto['id']}").content == PNG
    assert client.get(f"/midia/{oculta['id']}").status_code == 404
    assert client.get(f"/midia/{doc['id']}").status_code == 404  # documentos nunca
    detalhe = client.get(f"/imovel/{pub['codigo']}").text
    assert f"/midia/{foto['id']}" in detalhe and "youtube-nocookie.com/embed/dQw4w9WgXcQ" in detalhe
    assert "javascript:alert" not in detalhe and doc["id"] not in detalhe


# ------------------------------------------------------------------- Leads


def test_lead_vira_contato_tarefa_e_atendimento(client):
    carla, _ = _corretor(client)
    bruno, _ = _corretor(client, "bruno")
    client.put("/api/v1/equipe/fila", json=[
        {"usuarioId": carla, "status": "disponivel", "desde": "2026-10-16T08:00:00"},
        {"usuarioId": bruno, "status": "disponivel", "desde": "2026-10-16T08:05:00"}])  # fmt: skip
    imovel = _imovel(client)

    amanha = (agora() + timedelta(days=1)).date().isoformat()
    r = _lead(client, tipo="visita", imovel=imovel["codigo"], data_visita=amanha,
              horario_visita="15:00", retorno=f"/imovel/{imovel['codigo']}")  # fmt: skip
    assert (r.status_code, r.headers["location"]) == (303, "/obrigado")

    lead = client.get(f"{API}/leads").json()["itens"][0]
    assert (lead["tipo"], lead["status"], lead["corretorId"]) == ("visita", "emAtendimento", carla)
    assert lead["imovelId"] == imovel["id"] and lead["dataVisita"] == f"{amanha}T15:00:00"

    contato = client.get(f"/api/v1/crm/contatos/{lead['contatoId']}").json()
    assert (contato["origem"], contato["etapa"], contato["papeis"]) == ("site", "novo", ["lead"])
    assert (contato["celular"], contato["corretorResponsavel"]) == ("(21) 98888-7777", "Carla")
    evento = client.get(f"/api/v1/crm/eventos/{lead['eventoId']}").json()
    assert (evento["tipo"], evento["prioridade"], evento["imovelId"]) == ("visita", "alta", imovel["id"])
    assert evento["dataHora"] == f"{amanha}T15:00:00"
    atendimento = next(a for a in client.get("/api/v1/equipe/atendimentos").json()
                       if a["id"] == lead["atendimentoId"])  # fmt: skip
    assert (atendimento["origem"], atendimento["corretorId"]) == ("site", carla)
    fila = client.get("/api/v1/equipe/fila").json()
    assert [(i["usuarioId"], i["status"]) for i in fila] == [
        (bruno, "disponivel"), (carla, "emAtendimento")]

    # Mesmo cliente de novo (pelo telefone): mesmo contato; vai para o Bruno.
    _lead(client, email="", telefone="21988887777", tipo="anunciar")
    segundo = next(x for x in client.get(f"{API}/leads").json()["itens"] if x["tipo"] == "anunciar")
    assert (segundo["contatoId"], segundo["corretorId"]) == (lead["contatoId"], bruno)
    papeis = client.get(f"/api/v1/crm/contatos/{lead['contatoId']}").json()["papeis"]
    assert papeis == ["lead", "proprietario"]


def test_lead_sem_fila_e_sem_tarefa(client):
    cfg = client.get(f"{API}/configuracao").json()
    client.put(f"{API}/configuracao", json=cfg | {"distribuirNaFila": False, "criarTarefa": False})
    _lead(client)
    lead = client.get(f"{API}/leads").json()["itens"][0]
    assert (lead["status"], lead["corretorId"], lead["eventoId"]) == ("novo", None, None)


def test_validacoes_e_protecoes_do_formulario(client):
    def erro(**campos):
        r = _lead(client, retorno="/contato", **campos)
        assert r.status_code == 303 and "erro=" in r.headers["location"], r.headers
        return r.headers["location"]

    assert "Autorize" in client.get(erro(consentimento="")).text
    erro(email="", telefone="")
    erro(email="invalido")
    erro(tipo="visita", data_visita="2020-01-01")
    # Retorno para fora do site é ignorado.
    r = _lead(client, retorno="https://malicioso.com", consentimento="")
    assert r.headers["location"].startswith("/?erro=")
    # Robô (isca preenchida) não gera lead.
    assert _lead(client, empresa="Spam LTDA").headers["location"] == "/obrigado"
    assert client.get(f"{API}/leads").json()["total"] == 0

    for _ in range(5):
        assert _lead(client).headers["location"] == "/obrigado"
    assert "erro=" in _lead(client).headers["location"]  # limite por endereço
    assert client.get(f"{API}/leads").json()["total"] == 5


def test_gestao_dos_leads_e_permissoes(client):
    _lead(client)
    lead = client.get(f"{API}/leads").json()["itens"][0]
    carla, h_carla = _corretor(client)
    r = client.put(f"{API}/leads/{lead['id']}", json={
        "status": "convertido", "corretorId": carla, "observacao": "Fechou proposta"})  # fmt: skip
    assert (r.json()["status"], r.json()["corretorId"]) == ("convertido", carla)
    assert client.get(f"{API}/leads?status=convertido").json()["total"] == 1

    # Corretor vê os leads, mas não altera o site.
    assert client.get(f"{API}/leads", headers=h_carla).status_code == 200
    cfg = client.get(f"{API}/configuracao").json()
    assert client.put(f"{API}/configuracao", json=cfg, headers=h_carla).status_code == 403
    _, h_fin = _corretor(client, "fin", "financeiro")
    assert client.get(f"{API}/leads", headers=h_fin).status_code == 403

    assert client.delete(f"{API}/leads/{lead['id']}").status_code == 204
    assert client.get(f"{API}/leads").json()["total"] == 0


def test_endereco_do_servidor_leva_ao_site_da_associacao(client, imobiliaria, monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import create_app

    principal = "https://xn--associaoconectabci-7sb3f.com.br/"
    imovel = _imovel(client)  # antes: a imobiliária padrão muda a assinatura dos logins
    s = get_settings()
    monkeypatch.setattr(s, "imobiliaria_padrao", imobiliaria.slug)
    monkeypatch.setattr(s, "site_principal_url", principal)
    with TestClient(create_app(), follow_redirects=False) as servidor:  # sem X-Imobiliaria
        for caminho in ("/", "/imoveis", f"/imovel/{imovel['codigo']}", "/contato", "/sitemap.xml"):
            r = servidor.get(caminho)
            assert (r.status_code, r.headers["location"]) == (302, principal), caminho
        assert servidor.post("/enviar", data={"nome": "x"}).status_code == 302
        assert servidor.get("/robots.txt").text == "User-agent: *\nDisallow: /\n"
        # API, app de gestão, logo e portais seguem no endereço do servidor.
        assert servidor.get("/api/v1/marca").status_code == 200
        assert servidor.get("/logo").status_code == 200
        assert servidor.get("/inquilino/entrar").status_code == 200
    # Pelo domínio/cabeçalho da imobiliária, o site dela continua abrindo.
    assert client.get("/").status_code == 200
    assert "Disallow: /\n" not in client.get("/robots.txt").text
    monkeypatch.setattr(s, "site_principal_url", "")
    with TestClient(create_app(), follow_redirects=False) as servidor:
        assert servidor.get("/").status_code == 200  # sem o site institucional, como antes

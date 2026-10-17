import re
from datetime import timedelta

import pytest

from app.core.config import get_settings
from app.core.tempo import agora
from app.modules.arquivos import services as arquivos
from app.modules.inquilino import services as s
from tests.apoio import contato, imovel, novo_id

API = "/api/v1/portal-inquilino"
LOC = "/api/v1/locacao"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 50


@pytest.fixture(autouse=True)
def pasta(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "arquivos_dir", str(tmp_path))


def _contrato(client, cpf="529.982.247-25", nome="Ana Inquilina"):
    hoje = agora().date()
    inquilino = contato(client, nome, documento=cpf)
    dono = contato(client, "Dono")
    cid = novo_id()
    r = client.put(f"{LOC}/contratos/{cid}", json={
        "imovelId": imovel(client, finalidades=["locacao"], logradouro="Rua A", numero="10", cidade="Niterói"),
        "locatarioId": inquilino, "beneficiarios": [{"contatoId": dono, "percentual": 100}],
        "dataInicio": "2026-01-01", "valorAluguel": 3000, "diaVencimento": 10,
        "multaAtraso": 10, "jurosMes": 1})  # fmt: skip
    assert r.status_code == 201, r.text

    def cobranca(competencia, vencimento, **extra):
        r = client.put(f"{LOC}/cobrancas/{novo_id()}", json={
            "contratoId": cid, "competencia": competencia, "vencimento": vencimento,
            "itens": [{"descricao": "Aluguel", "valor": 3000, "tipo": "aluguel"},
                      {"descricao": "Condomínio", "valor": 500, "tipo": "despesa"}], **extra})  # fmt: skip
        assert r.status_code == 201, r.text
        return r.json()["id"]

    ids = {
        "paga": cobranca("2026-01-01", "2026-01-10", status="paga",
                         dataPagamento="2026-01-09", valorPago=3500),  # fmt: skip
        "vencida": cobranca(f"{(hoje - timedelta(days=40)):%Y-%m}-01", (hoje - timedelta(days=5)).isoformat()),
        "aberta": cobranca(f"{(hoje + timedelta(days=40)):%Y-%m}-01", (hoje + timedelta(days=20)).isoformat()),
    }
    return cid, inquilino, ids


def _entrar(client, cpf, senha):
    return client.post("/inquilino/entrar", data={"documento": cpf, "senha": senha}, follow_redirects=False)


def _csrf(client, pagina="/inquilino"):
    return re.search(r'name="csrf" value="([^"]+)"', client.get(pagina).text).group(1)


def _liberado(client, cpf="529.982.247-25", nome="Ana Inquilina"):
    """Contrato + acesso liberado + senha trocada; já logado."""
    cid, inquilino, ids = _contrato(client, cpf, nome)
    provisoria = client.post(f"{API}/acessos/{inquilino}").json()["senha"]
    _entrar(client, cpf, provisoria)
    csrf = _csrf(client, "/inquilino/senha")
    r = client.post("/inquilino/senha", data={"atual": provisoria, "nova": "senha-nova-123",
                                              "repetida": "senha-nova-123", "csrf": csrf},
                    follow_redirects=False)  # fmt: skip
    assert r.headers["location"].startswith("/inquilino?ok="), r.headers
    return cid, inquilino, ids


def test_acesso_senha_provisoria_e_bloqueio(client):
    _, inquilino, _ = _contrato(client)
    sem_cpf = contato(client, "Sem CPF")
    assert client.post(f"{API}/acessos/{sem_cpf}").json()["detail"].startswith("Cadastre o CPF")

    liberado = client.post(f"{API}/acessos/{inquilino}").json()
    assert liberado["login"] == "52998224725" and len(liberado["senha"]) == 10
    assert client.get("/inquilino", follow_redirects=False).headers["location"] == "/inquilino/entrar"

    erro = _entrar(client, "529.982.247-25", "errada")
    assert "erro=" in erro.headers["location"]
    r = _entrar(client, "52998224725", liberado["senha"])
    assert r.headers["location"] == "/inquilino/senha"  # troca obrigatória
    assert client.get("/inquilino", follow_redirects=False).headers["location"] == "/inquilino/senha"

    # Sem o token CSRF, nada muda.
    r = client.post("/inquilino/senha", data={"atual": liberado["senha"], "nova": "x" * 8, "repetida": "x" * 8},
                    follow_redirects=False)  # fmt: skip
    assert "Sess%C3%A3o+expirada" in r.headers["location"]

    # Nova senha provisória derruba a sessão aberta.
    nova = client.post(f"{API}/acessos/{inquilino}").json()["senha"]
    assert client.get("/inquilino/senha", follow_redirects=False).headers["location"] == "/inquilino/entrar"
    client.cookies.clear()
    for _ in range(s.TENTATIVAS):
        _entrar(client, "52998224725", "errada")
    r = _entrar(client, "52998224725", nova)  # certa, mas bloqueada
    assert "Muitas+tentativas" in r.headers["location"]
    acessos = client.get(f"{API}/acessos").json()
    assert acessos[0]["bloqueado"] is True and acessos[0]["trocarSenha"] is True

    assert client.delete(f"{API}/acessos/{inquilino}").status_code == 204
    assert client.get(f"{API}/acessos").json() == []


def test_painel_pagamentos_e_boleto_com_pix(client):
    client.put("/api/v1/personalizacao/empresa", json={
        "nome": "Marcelo Bonifácio Imóveis", "chavePix": "11222333000181",
        "endereco": "Rua Moreira César, 100 - Icaraí, Niterói/RJ"})  # fmt: skip
    cid, _, ids = _liberado(client)

    painel = client.get("/inquilino")
    assert painel.status_code == 200 and painel.headers["cache-control"] == "no-store"
    assert "R$ 7.000" in painel.text  # em aberto: vencida + aberta
    assert "1 vencida" in painel.text

    pag = client.get("/inquilino/pagamentos").text
    assert "Vencida" in pag and "5 dias de atraso" in pag and "Recibo" in pag

    boleto = client.get(f"/inquilino/boleto/{ids['vencida']}").text
    assert "BOLETO DE ALUGUEL" in boleto and "Condomínio" in boleto and "R$ 3.500" in boleto
    pix = re.search(r'<textarea id="pix" readonly>([^<]+)</textarea>', boleto).group(1)
    assert pix.startswith("000201") and "br.gov.bcb.pix" in pix and "11222333000181" in pix
    assert "5303986" in pix and "6007NITEROI" in pix
    assert s._crc16(pix[:-4]) == pix[-4:]  # CRC confere
    recibo = client.get(f"/inquilino/boleto/{ids['paga']}").text
    assert "RECIBO DE PAGAMENTO" in recibo and "textarea" not in recibo


def test_crc_do_pix():
    assert s._crc16("123456789") == "29B1"  # CRC-16/CCITT-FALSE


def test_inquilino_so_ve_o_proprio_contrato(client):
    _, _, ids_ana = _contrato(client, "529.982.247-25", "Ana")
    client.cookies.clear()
    _liberado(client, "111.444.777-35", "Bruno")
    assert client.get(f"/inquilino/boleto/{ids_ana['aberta']}").status_code == 404
    assert "Ana" not in client.get("/inquilino").text


def test_documentos_publicados_e_envios_do_inquilino(client, banco):
    cid, _, _ = _liberado(client)
    up = client.post("/api/v1/arquivos", data={"categoria": "arquivo"},
                     files={"arquivo": ("contrato.pdf", b"%PDF-1.4 contrato")}).json()  # fmt: skip
    doc = novo_id()
    r = client.put(f"{API}/arquivos/{doc}", json={
        "contratoId": cid, "tipo": "contrato", "titulo": "Contrato assinado",
        "referencia": up["referencia"]})  # fmt: skip
    assert r.status_code == 201
    oculto = novo_id()
    client.put(f"{API}/arquivos/{oculto}", json={
        "contratoId": cid, "tipo": "documento", "titulo": "Rascunho interno",
        "referencia": up["referencia"], "visivelInquilino": False})  # fmt: skip

    pagina = client.get("/inquilino/documentos").text
    assert "Contrato assinado" in pagina and "Rascunho interno" not in pagina
    assert client.get(f"/inquilino/arquivo/{doc}").content == b"%PDF-1.4 contrato"
    assert client.get(f"/inquilino/arquivo/{oculto}").status_code == 404
    avisos = client.get("/inquilino/avisos").text
    assert "Novo documento disponível" in avisos

    csrf = _csrf(client, "/inquilino/documentos")
    r = client.post("/inquilino/documentos", data={"csrf": csrf, "descricao": "Sala na entrada"},
                    files=[("arquivos", ("sala.png", PNG)), ("arquivos", ("tour.mp4", MP4))],
                    follow_redirects=False)  # fmt: skip
    assert "ok=" in r.headers["location"], r.headers
    r = client.post("/inquilino/documentos", data={"csrf": csrf},
                    files=[("arquivos", ("virus.exe", b"MZ"))], follow_redirects=False)  # fmt: skip
    assert "erro=" in r.headers["location"]

    enviados = [a for a in client.get(f"{API}/arquivos", params={"contratoId": cid}).json()
                if a["origem"] == "inquilino"]  # fmt: skip
    assert {a["tipo"] for a in enviados} == {"estadoImovel"} and len(enviados) == 2
    tarefas = client.get("/api/v1/crm/eventos").json()["itens"]
    assert any("enviou 2 foto(s)/vídeo(s)" in t["titulo"] for t in tarefas)

    # A limpeza de arquivos não apaga o que está ligado ao contrato.
    with banco() as db:
        assert arquivos.limpar_orfaos(db, carencia=timedelta(0)) == 0


def test_chamado_vira_manutencao_e_avisa_o_andamento(client):
    cid, _, _ = _liberado(client)
    csrf = _csrf(client, "/inquilino/chamados")
    curta = client.post("/inquilino/chamados", data={"csrf": csrf, "tipo": "eletrica", "descricao": "luz"},
                        follow_redirects=False)  # fmt: skip
    assert "erro=" in curta.headers["location"]
    r = client.post("/inquilino/chamados",
                    data={"csrf": csrf, "tipo": "eletrica", "descricao": "Tomada da sala soltando faísca"},
                    files=[("arquivos", ("tomada.png", PNG))], follow_redirects=False)  # fmt: skip
    assert "ok=" in r.headers["location"]

    pauta = client.get("/api/v1/manutencoes").json()["itens"]
    assert len(pauta) == 1
    chamado = pauta[0]
    assert (chamado["contratoId"], chamado["origem"], chamado["tipo"], chamado["status"]) == (
        cid, "inquilino", "eletrica", "pendente")
    anexos = client.get(f"{API}/arquivos", params={"manutencaoId": chamado["id"]}).json()
    assert len(anexos) == 1 and anexos[0]["tipo"] == "chamado"

    # A gestão (app antigo, sem contratoId no corpo) muda o status: o vínculo continua.
    corpo = {k: v for k, v in chamado.items() if k not in ("contratoId", "origem", "id", "criadoEm", "atualizadoEm")}
    corpo |= {"status": "emAndamento", "dataPrevista": "2026-12-01"}
    salvo = client.put(f"/api/v1/manutencoes/{chamado['id']}", json=corpo).json()
    assert (salvo["status"], salvo["contratoId"], salvo["origem"]) == ("emAndamento", cid, "inquilino")

    pagina = client.get("/inquilino/chamados").text
    assert "Em andamento" in pagina and "Tomada da sala" in pagina
    avisos = client.get("/inquilino/avisos").text
    assert "está em andamento" in avisos and "01/12/2026" in avisos
    assert '<span class="selo-num">' not in client.get("/inquilino/avisos").text  # já lidos


def test_comunicados_da_equipe(client):
    cid, _, _ = _liberado(client)
    client.post(f"{API}/comunicados", json={"titulo": "Manutenção do elevador", "mensagem": "Dia 20, das 9h às 12h."})
    client.post(f"{API}/comunicados", json={"contratoId": cid, "titulo": "Reajuste", "mensagem": "IGP-M aplicado."})
    assert '<span class="selo-num">2</span>' in client.get("/inquilino").text
    pagina = client.get("/inquilino/avisos").text
    assert "Manutenção do elevador" in pagina and "para todos os inquilinos" in pagina
    lidos = {c["titulo"]: c["leituras"] for c in client.get(f"{API}/comunicados").json()}
    assert lidos == {"Manutenção do elevador": 1, "Reajuste": 1}


def test_area_desligada_no_site(client):
    cfg = client.get("/api/v1/site/configuracao").json()
    client.put("/api/v1/site/configuracao", json=cfg | {"mostrarAreaInquilino": False})
    assert client.get("/inquilino/entrar").status_code == 503
    assert "Área do inquilino" not in client.get("/").text

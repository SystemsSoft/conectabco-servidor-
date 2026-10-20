import base64
import json

import httpx
import pytest

from app.modules.sicoob import cliente
from tests.apoio import contato, imovel, novo_id

API = "/api/v1/integracoes/sicoob"
PDF = b"%PDF-1.4 boleto"


class SicoobFalso:
    """Imita o Sandbox do Sicoob e guarda as requisições recebidas."""

    def __init__(self):
        self.pedidos: list[httpx.Request] = []
        self.recusar = False

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.pedidos.append(req)
        if self.recusar:
            return httpx.Response(401, json={"message": "Unauthorized"})
        p = req.url.path
        if p.endswith("/cobranca-bancaria/v3/boletos") and req.method == "POST":
            corpo = json.loads(req.content)
            return httpx.Response(200, json={"resultado": {
                **corpo, "nossoNumero": 123456, "linhaDigitavel": "75691.23456 00001.234567 8",
                "codigoBarras": "75691234500000150001234567", "situacaoBoleto": "Em Aberto",
                "pdfBoleto": base64.b64encode(PDF).decode()}})  # fmt: skip
        if p.endswith("/cobranca-bancaria/v3/boletos") and req.method == "GET":
            return httpx.Response(200, json={"resultado": {"nossoNumero": 123456, "situacaoBoleto": "Liquidado"}})
        if p.endswith("/boletos/segunda-via"):
            return httpx.Response(200, json={"resultado": {"pdfBoleto": base64.b64encode(PDF).decode()}})
        if p.endswith("/boletos/123456/baixar"):
            return httpx.Response(204)
        if "/pix/api/v2/cob/" in p and req.method == "PUT":
            txid = p.rsplit("/", 1)[1]
            return httpx.Response(201, json={"txid": txid, "status": "ATIVA", "location": "pix.sicoob/qr/1",
                                             "pixCopiaECola": "00020126580014br.gov.bcb.pix0136teste"})  # fmt: skip
        if "/pix/api/v2/cob/" in p:
            return httpx.Response(200, json={"status": "CONCLUIDA", "pixCopiaECola": "000201"})
        if p.endswith("/pix/api/v2/cob"):
            return httpx.Response(200, json={"cobs": []})
        if p.endswith("/pix/api/v2/pix"):
            return httpx.Response(200, json={"pix": [{"endToEndId": "E1", "txid": "abc", "valor": "150.00",
                                                     "horario": "2026-10-19T10:00:00Z",
                                                     "pagador": {"nome": "Ana"}}]})  # fmt: skip
        if p.endswith("/conta-corrente/v4/saldo"):
            return httpx.Response(200, json={"resultado": {"saldo": "4302.49", "saldoLimite": "5000.00",
                                                           "saldoBloqueado": "0.00"}})  # fmt: skip
        if "/conta-corrente/v4/extrato/" in p:
            return httpx.Response(200, json={"resultado": {
                "saldoAnterior": "2244.12", "saldoAtual": "4302.49", "transacoes": [
                    {"tipo": "CREDITO", "valor": "3000.00", "data": "2026-10-05T00:00:00",
                     "descricao": "PIX RECEBIDO", "numeroDocumento": "Pix", "descInfComplementar": "Aluguel"},
                    {"tipo": "DEBITO", "valor": "250.00", "data": "2026-10-06T00:00:00",
                     "descricao": "TARIFA", "numeroDocumento": "TAR"}]}})  # fmt: skip
        return httpx.Response(404, json={"mensagens": [{"mensagem": "Rota desconhecida"}]})


@pytest.fixture
def sicoob(monkeypatch):
    falso = SicoobFalso()
    monkeypatch.setattr(cliente, "transporte_padrao", lambda: httpx.MockTransport(falso))
    return falso


def _configurar(client, **extra):
    r = client.put(f"{API}/configuracao", json={
        "clientId": "cid-sandbox", "token": "tok-secreto", "numeroCliente": "25546454",
        "codigoModalidade": 1, "numeroContaCorrente": "0", "chavePix": "imob@pix.com", **extra})  # fmt: skip
    assert r.status_code == 200, r.text
    return r.json()


def test_configuracao_nao_expoe_o_token(client, sicoob):
    assert client.post(f"{API}/testar").json()["detail"].startswith("Informe o client_id")
    cfg = _configurar(client)
    assert cfg["tokenConfigurado"] is True and "token" not in cfg
    # Salvar sem token mantém o atual.
    cfg = client.put(f"{API}/configuracao", json={**cfg, "token": ""}).json()
    assert cfg["tokenConfigurado"] is True
    r = client.put(f"{API}/configuracao", json={**cfg, "ambiente": "producao"})
    assert r.status_code == 200
    assert "Produção ainda não está habilitada" in client.post(f"{API}/testar").json()["detail"]


def test_testar_conexao_e_registro_sem_token(client, sicoob):
    _configurar(client)
    r = client.post(f"{API}/testar").json()
    assert [x["api"] for x in r] == ["cobranca", "pix", "conta"]
    assert all(x["ok"] for x in r)
    req = sicoob.pedidos[0]
    assert req.headers["client_id"] == "cid-sandbox" and req.headers["authorization"] == "Bearer tok-secreto"
    assert str(req.url).startswith("https://sandbox.sicoob.com.br/sicoob/sandbox/cobranca-bancaria/v3/boletos")

    sicoob.recusar = True
    r = client.post(f"{API}/testar").json()
    assert not any(x["ok"] for x in r) and "recusadas" in r[0]["mensagem"]
    chamadas = client.get(f"{API}/chamadas").json()
    assert len(chamadas) == 6 and chamadas[0]["statusHttp"] == 401
    detalhe = client.get(f"{API}/chamadas/{chamadas[0]['id']}").json()
    assert "tok-secreto" not in json.dumps(detalhe)


def test_boleto_a_partir_da_cobranca_do_aluguel(client, sicoob):
    _configurar(client)
    dono = contato(client, "Dono")
    inq = contato(client, "Ana Inquilina", documento="529.982.247-25", cep="24000-000",
                  logradouro="Rua A", numero="10", bairro="Centro", cidade="Niterói", uf="RJ")
    im = imovel(client, finalidades=["locacao"])
    cid = novo_id()
    assert client.put(f"/api/v1/locacao/contratos/{cid}", json={
        "imovelId": im, "locatarioId": inq, "beneficiarios": [{"contatoId": dono, "percentual": 100}],
        "dataInicio": "2026-01-01", "valorAluguel": 1500, "diaVencimento": 10}).status_code == 201  # fmt: skip
    cob = novo_id()
    assert client.put(f"/api/v1/locacao/cobrancas/{cob}", json={
        "contratoId": cid, "competencia": "2099-11-01", "vencimento": "2099-11-10",
        "itens": [{"descricao": "Aluguel", "valor": 1500, "tipo": "aluguel"}]}).status_code == 201  # fmt: skip

    abertas = client.get(f"{API}/cobrancas-abertas").json()
    assert [a["id"] for a in abertas] == [cob] and abertas[0]["locatario"] == "Ana Inquilina"
    rasc = client.get(f"{API}/rascunho", params={"cobrancaId": cob}).json()
    assert rasc["valor"] == 1500 and rasc["pagador"]["documento"] == "52998224725"
    assert rasc["multaPercentual"] == 10 and rasc["pagador"]["cep"] == "24000000"

    r = client.post(f"{API}/boletos", json={
        "valor": rasc["valor"], "vencimento": rasc["vencimento"], "pagador": rasc["pagador"],
        "multaPercentual": 2, "jurosMesPercentual": 1, "mensagem": "Aluguel", "cobrancaId": cob})  # fmt: skip
    assert r.status_code == 201, r.text
    b = r.json()["boleto"]
    assert b["nossoNumero"] == "123456" and base64.b64decode(r.json()["pdf"]) == PDF
    corpo = json.loads(sicoob.pedidos[-1].content)
    assert corpo["numeroCliente"] == 25546454 and corpo["tipoMulta"] == 2 and corpo["valorMulta"] == 2
    assert corpo["tipoJurosMora"] == 2 and corpo["dataMulta"] == "2099-11-11"
    assert corpo["pagador"]["numeroCpfCnpj"] == "52998224725" and corpo["codigoCadastrarPIX"] == 1

    assert client.post(f"{API}/boletos/{b['id']}/consultar").json()["situacao"] == "Liquidado"
    assert base64.b64decode(client.get(f"{API}/boletos/{b['id']}/pdf").json()["pdf"]) == PDF
    assert client.post(f"{API}/boletos/{b['id']}/baixar").json()["situacao"] == "Baixado"
    assert len(client.get(f"{API}/boletos").json()) == 1

    # Validações locais (nada vai ao banco).
    antes = len(sicoob.pedidos)
    ruim = client.post(f"{API}/boletos", json={"valor": 10, "vencimento": "2000-01-01",
                                               "pagador": {"documento": "123", "nome": "X"}})  # fmt: skip
    assert ruim.json()["detail"] == "CPF/CNPJ do pagador inválido." and len(sicoob.pedidos) == antes


def test_pix_cobranca_qrcode_e_recebidos(client, sicoob):
    _configurar(client)
    r = client.post(f"{API}/pix", json={"valor": 150, "devedorDocumento": "529.982.247-25",
                                        "devedorNome": "Ana", "descricao": "Aluguel out/26"})  # fmt: skip
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["copiaECola"].startswith("000201") and p["qrCodePng"].startswith("data:image/png;base64,")
    put = sicoob.pedidos[-1]
    corpo = json.loads(put.content)
    assert put.method == "PUT" and len(p["txid"]) == 35
    assert corpo["valor"]["original"] == "150.00" and corpo["devedor"] == {"cpf": "52998224725", "nome": "Ana"}
    assert corpo["chave"] == "imob@pix.com" and corpo["calendario"]["expiracao"] == 86400
    assert client.post(f"{API}/pix/{p['id']}/consultar").json()["status"] == "CONCLUIDA"
    rec = client.get(f"{API}/pix-recebidos", params={"inicio": "2026-10-01", "fim": "2026-10-19"}).json()
    assert rec[0]["valor"] == 150 and rec[0]["pagador"] == "Ana"
    assert "31 dias" in client.get(f"{API}/pix-recebidos", params={"inicio": "2026-01-01", "fim": "2026-03-01"}).json()["detail"]


def test_saldo_extrato_e_importacao_para_conciliacao(client, sicoob):
    _configurar(client)
    assert client.get(f"{API}/saldo").json()["saldo"] == 4302.49
    ext = client.get(f"{API}/extrato", params={"mes": 10, "ano": 2026}).json()
    assert len(ext["transacoes"]) == 2 and ext["saldoAtual"] == 4302.49
    assert "conta do Financeiro" in client.post(f"{API}/extrato/importar", json={"mes": 10, "ano": 2026}).json()["detail"]

    conta = novo_id()
    assert client.put(f"/api/v1/financeiro/contas-bancarias/{conta}", json={"nome": "Sicoob"}).status_code in (200, 201)
    cfg = client.get(f"{API}/configuracao").json()
    client.put(f"{API}/configuracao", json={**cfg, "contaBancariaId": conta})
    assert client.post(f"{API}/extrato/importar", json={"mes": 10, "ano": 2026}).json() == {"importadas": 2, "repetidas": 0}
    assert client.post(f"{API}/extrato/importar", json={"mes": 10, "ano": 2026}).json() == {"importadas": 0, "repetidas": 2}


def _linha(campos: dict[tuple[int, int], str]) -> str:
    """Monta uma linha CNAB 240 a partir de {(inicio, fim): valor} (posições de 1)."""
    s = [" "] * 240
    for (ini, fim), v in campos.items():
        v = v.rjust(fim - ini + 1, "0") if v.isdigit() else v.ljust(fim - ini + 1)
        s[ini - 1 : fim] = v[: fim - ini + 1]
    return "".join(s)


def _cnab(*titulos: tuple[str, str, int, str]) -> bytes:
    """titulos = (movimento, nosso número, valor pago em centavos, data DDMMAAAA)."""
    ls = [_linha({(1, 3): "756", (8, 8): "0", (73, 102): "IMOBILIARIA TESTE"}),
          _linha({(1, 3): "756", (8, 8): "1"})]  # fmt: skip
    for i, (mov, nn, pago, dt) in enumerate(titulos):
        ls.append(_linha({(1, 3): "756", (8, 8): "3", (9, 13): str(2 * i + 1), (14, 14): "T", (16, 17): mov,
                          (38, 57): nn.rjust(10, "0"), (59, 73): "DOC", (74, 81): "10112099",
                          (82, 96): str(pago)}))  # fmt: skip
        ls.append(_linha({(1, 3): "756", (8, 8): "3", (9, 13): str(2 * i + 2), (14, 14): "U",
                          (78, 92): str(pago), (138, 145): dt, (146, 153): dt}))  # fmt: skip
    ls += [_linha({(1, 3): "756", (8, 8): "5"}), _linha({(1, 3): "756", (8, 8): "9"})]
    return "\r\n".join(ls).encode("latin-1")


def test_retorno_cnab_da_baixa_na_cobranca_do_aluguel(client, sicoob):
    _configurar(client)
    dono = contato(client, "Dono")
    inq = contato(client, "Ana Inquilina", documento="529.982.247-25")
    im = imovel(client, finalidades=["locacao"])
    cid = novo_id()
    client.put(f"/api/v1/locacao/contratos/{cid}", json={
        "imovelId": im, "locatarioId": inq, "beneficiarios": [{"contatoId": dono, "percentual": 100}],
        "dataInicio": "2026-01-01", "valorAluguel": 1500, "diaVencimento": 10})  # fmt: skip
    cob = novo_id()
    client.put(f"/api/v1/locacao/cobrancas/{cob}", json={
        "contratoId": cid, "competencia": "2099-11-01", "vencimento": "2099-11-10",
        "itens": [{"descricao": "Aluguel", "valor": 1500, "tipo": "aluguel"}]})  # fmt: skip
    r = client.post(f"{API}/boletos", json={"valor": 1500, "vencimento": "2099-11-10", "cobrancaId": cob,
                                            "pagador": {"documento": "52998224725", "nome": "Ana"}})  # fmt: skip
    assert r.status_code == 201, r.text

    # Nosso número 123456 com dígito verificador (1234567); um título desconhecido; uma entrada confirmada.
    arquivo = _cnab(("06", "1234567", 153000, "12112099"), ("06", "999", 5000, "12112099"),
                    ("02", "123456", 0, "01112099"))  # fmt: skip
    corpo = {"conteudo": base64.b64encode(arquivo).decode()}
    previa = client.post(f"{API}/retorno", json=corpo).json()
    assert [i["situacao"] for i in previa["itens"]] == ["baixar", "sem_boleto", "ignorado"]
    assert previa["itens"][0]["locatario"] == "Ana Inquilina" and previa["baixas"] == 1
    assert client.get(f"/api/v1/locacao/cobrancas/{cob}").json()["status"] == "aberta"

    feito = client.post(f"{API}/retorno", json={**corpo, "aplicar": True}).json()
    assert feito["aplicado"] and feito["itens"][0]["situacao"] == "aplicada"
    c = client.get(f"/api/v1/locacao/cobrancas/{cob}").json()
    assert (c["status"], c["dataPagamento"], c["valorPago"]) == ("paga", "2099-11-12", 1530)
    assert client.get(f"{API}/boletos").json()[0]["situacao"] == "Liquidado"
    # Reenviar o mesmo arquivo não paga de novo.
    assert client.post(f"{API}/retorno", json={**corpo, "aplicar": True}).json()["itens"][0]["situacao"] == "ja_paga"

    # Arquivos errados.
    erro = lambda b: client.post(f"{API}/retorno", json={"conteudo": base64.b64encode(b).decode()}).json()["detail"]  # noqa: E731
    assert "CNAB 400" in erro(("0" * 400 + "\n").encode())
    assert "banco 341" in erro(arquivo.replace(b"756", b"341"))

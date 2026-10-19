import re
from datetime import timedelta

import pytest
import sqlalchemy as sa

from app.core.config import get_settings
from app.core.tempo import agora
from app.modules.arquivos import services as arquivos
from app.modules.auditoria import transcricao
from app.modules.auditoria.models import MidiaAuditoria
from app.modules.equipe.enums import PerfilAcesso, permissoes_do_perfil
from app.modules.manutencao.models import Manutencao
from app.modules.proprietario import services as prop
from tests.apoio import contato, imovel, novo_id

API = "/api/v1/auditorias"
LOC = "/api/v1/locacao"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100
MP4 = b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 50


@pytest.fixture(autouse=True)
def pasta(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "arquivos_dir", str(tmp_path))


class TranscritorFalso:
    def __init__(self, texto="Na cozinha a torneira está pingando e precisa de reparo."):
        self.texto, self.chamadas = texto, []

    def transcrever(self, caminho):
        self.chamadas.append(caminho)
        return self.texto


def _cenario(client, cpf_dono="529.982.247-25", **dono):
    hoje = agora().date()
    proprietario = contato(client, "Roberto Proprietário", documento=cpf_dono, **dono)
    inquilino = contato(client, "Ana Inquilina")
    im = imovel(client, finalidades=["locacao"], logradouro="Rua A", numero="10", cidade="Niterói")
    cid = novo_id()
    r = client.put(f"{LOC}/contratos/{cid}", json={
        "imovelId": im, "locatarioId": inquilino,
        "beneficiarios": [{"contatoId": proprietario, "percentual": 100}],
        "dataInicio": f"{hoje.year - 1}-01-01", "valorAluguel": 3000, "diaVencimento": 10,
        "taxaAdministracao": 10})  # fmt: skip
    assert r.status_code == 201, r.text
    return proprietario, inquilino, im, cid


def _cobranca(client, cid, competencia, vencimento, **extra):
    r = client.put(f"{LOC}/cobrancas/{novo_id()}", json={
        "contratoId": cid, "competencia": competencia, "vencimento": vencimento,
        "itens": [{"descricao": "Aluguel", "valor": 3000, "tipo": "aluguel"}], **extra})  # fmt: skip
    assert r.status_code == 201, r.text
    return r.json()["id"]


def _auditoria(client, im, cid=None, **extra):
    aid = novo_id()
    itens = [{"id": novo_id(), "area": "Cozinha", "item": "Torneiras e sifão"},
             {"id": novo_id(), "area": "Sala", "item": "Paredes e teto"}]  # fmt: skip
    r = client.put(f"{API}/{aid}", json={"imovelId": im, "contratoId": cid, "itens": itens, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def _upload(client, nome, conteudo, categoria):
    return client.post("/api/v1/arquivos", data={"categoria": categoria},
                       files={"arquivo": (nome, conteudo)}).json()["referencia"]  # fmt: skip


def test_ciclo_da_auditoria_bloqueio_e_publicacao(client):
    dono, _, im, cid = _cenario(client)
    a = _auditoria(client, im, cid, dataAgendada="2026-10-20")
    assert (a["numero"], a["status"], a["proprietarioId"]) == ("AUD-0001", "agendada", dono)
    outro = imovel(client)
    r = client.put(f"{API}/{novo_id()}", json={"imovelId": outro, "contratoId": cid})
    assert r.json()["detail"] == "O contrato escolhido é de outro imóvel."

    r = client.post(f"{API}/{a['id']}/concluir", json={"publicar": True})
    assert r.json()["detail"] == "Avalie todos os itens do checklist (2 sem avaliação)."
    a["itens"][0] |= {"estado": "problema", "observacao": "Sifão vazando"}
    a["itens"][1] |= {"estado": "ok"}
    corpo = {"imovelId": im, "contratoId": cid, "status": "emAndamento", "itens": a["itens"],
             "resumo": "Imóvel bem conservado.", "recomendacoes": "Trocar o sifão."}  # fmt: skip
    client.put(f"{API}/{a['id']}", json=corpo)
    assert client.post(f"{API}/{a['id']}/concluir", json={}).json()["detail"].startswith("Dê a nota")
    client.put(f"{API}/{a['id']}", json=corpo | {"nota": 4})
    r = client.post(f"{API}/{a['id']}/publicacao", json={"publicada": True})
    assert r.json()["detail"].startswith("Conclua a auditoria")
    concluida = client.post(f"{API}/{a['id']}/concluir", json={"publicar": True}).json()
    assert (concluida["status"], concluida["publicada"]) == ("concluida", True)
    assert concluida["dataRealizada"] == agora().date().isoformat()

    # Concluída = bloqueada (edição, mídia e exclusão).
    assert "não pode ser alterada" in client.put(f"{API}/{a['id']}", json=corpo).json()["detail"]
    assert client.delete(f"{API}/{a['id']}").status_code == 422

    # Problema vira manutenção ligada ao contrato (uma vez só).
    r = client.post(f"{API}/{a['id']}/manutencoes").json()
    assert r["criadas"] == 1 and r["auditoria"]["itens"][0]["manutencaoId"]
    pauta = client.get("/api/v1/manutencoes").json()["itens"]
    assert pauta[0]["descricao"] == "Cozinha – Torneiras e sifão: Sifão vazando"
    assert pauta[0]["contratoId"] == cid
    assert client.post(f"{API}/{a['id']}/manutencoes").status_code == 422

    reaberta = client.post(f"{API}/{a['id']}/reabrir").json()
    assert (reaberta["status"], reaberta["publicada"]) == ("emAndamento", False)


def test_videos_fila_de_transcricao_e_relatorio(client, banco):
    _, _, im, cid = _cenario(client)
    a = _auditoria(client, im, cid)
    video, foto = novo_id(), novo_id()
    ref_video = _upload(client, "cozinha.mp4", MP4, "video")
    ref_foto = _upload(client, "sala.png", PNG, "foto")
    r = client.put(f"{API}/{a['id']}/midias/{foto}", json={"referencia": ref_video, "tipo": "foto"})
    assert r.json()["detail"] == "O arquivo enviado não é do tipo informado (foto/vídeo)."
    client.put(f"{API}/{a['id']}/midias/{foto}", json={"referencia": ref_foto, "tipo": "foto",
                                                       "titulo": "Sala", "itemId": a["itens"][1]["id"]})  # fmt: skip
    client.put(f"{API}/{a['id']}/midias/{video}", json={"referencia": ref_video, "tipo": "video",
                                                        "titulo": "Cozinha"})  # fmt: skip
    assert client.post(f"{API}/{a['id']}/midias/{foto}/transcrever").json()["detail"] == (
        "Só vídeos podem ser transcritos.")
    r = client.post(f"{API}/{a['id']}/midias/{video}/transcrever").json()
    assert next(x for x in r["midias"] if x["id"] == video)["transcricaoStatus"] == "pendente"
    assert client.post(f"{API}/{a['id']}/midias/{video}/transcrever").status_code == 422

    falso = TranscritorFalso()
    assert transcricao.rodar(banco, falso, uma_vez=True) == 1
    assert len(falso.chamadas) == 1 and falso.chamadas[0].endswith(ref_video.removeprefix("arquivo:"))
    v = next(x for x in client.get(f"{API}/{a['id']}").json()["midias"] if x["id"] == video)
    assert (v["transcricaoStatus"], v["transcricaoTexto"]) == ("concluida", falso.texto)

    # Relatório da equipe (link assinado) com a transcrição.
    link = client.post(f"{API}/{a['id']}/relatorio").json()["link"]
    pagina = client.get(link).text
    assert "RELATÓRIO DE AUDITORIA" in pagina and falso.texto in pagina and "Torneiras e sifão" in pagina
    assert client.get(link.replace("assinatura=", "assinatura=x")).status_code == 404

    # Erro (arquivo sumiu) fica registrado; processando preso volta à fila.
    with banco() as db:
        m = db.get(MidiaAuditoria, video)
        arquivos.caminho(m.arquivo_id).unlink()
        m.transcricao_status = m.transcricao_status.__class__.processando
        db.commit()
        assert transcricao.recuperar_interrompidas(db) == 1
    transcricao.rodar(banco, falso, uma_vez=True)
    v = next(x for x in client.get(f"{API}/{a['id']}").json()["midias"] if x["id"] == video)
    assert v["transcricaoStatus"] == "erro" and "não encontrado" in v["transcricaoErro"]

    # A limpeza diária não apaga mídias de auditoria.
    with banco() as db:
        assert arquivos.limpar_orfaos(db, carencia=timedelta(0)) == 0


def test_pendencias_automaticas_e_visao_por_proprietario(client, banco):
    hoje = agora().date()
    dono, _, im, cid = _cenario(client, cpf_dono="")  # sem CPF nem dados bancários
    paga = _cobranca(client, cid, f"{hoje.year}-01-01", (hoje - timedelta(days=20)).isoformat(),
                     status="paga", dataPagamento=(hoje - timedelta(days=15)).isoformat(),
                     valorPago=3000)  # fmt: skip
    _cobranca(client, cid, f"{(hoje - timedelta(days=40)):%Y-%m}-01", (hoje - timedelta(days=40)).isoformat())
    with banco() as db:  # chamado do inquilino parado há 3 dias
        db.add(Manutencao(id=novo_id(), contexto="locacao", imovel_id=im, tipo="eletrica",
                          descricao="Tomada queimada", contrato_id=cid, origem="inquilino",
                          criado_em=agora() - timedelta(days=3)))  # fmt: skip
        db.commit()

    lista = client.get(f"{API}/pendencias").json()
    titulos = {p["titulo"]: p["gravidade"] for p in lista}
    assert titulos[f"Repasse pendente – 01/{hoje.year}"] == "critica"  # 15 dias > 2 × 5
    assert titulos["Aluguel em atraso há 40 dias"] == "critica"
    assert titulos["Chamado do inquilino sem resposta"] == "critica"
    assert titulos["Laudo de vistoria não publicado"] == "atencao"
    assert titulos["Imóvel nunca auditado em campo"] == "atencao"
    assert titulos["Proprietário sem CPF/CNPJ"] == "atencao"
    assert titulos["Proprietário sem dados para repasse"] == "atencao"
    assert all(p["proprietarioId"] == dono for p in lista)

    # Repasse feito: a pendência some.
    client.put(f"{LOC}/repasses/{paga}/{dono}", json={"data": hoje.isoformat()})
    assert not any(p["titulo"].startswith("Repasse") for p in client.get(f"{API}/pendencias").json())

    resumo = client.get(f"{API}/proprietarios").json()[0]
    assert (resumo["contatoId"], resumo["saude"], resumo["aluguelMensal"], resumo["emAtraso"]) == (
        dono, "vermelho", 3000, 3000)

    # Prazos configuráveis.
    cfg = client.get(f"{API}/configuracao").json()
    client.put(f"{API}/configuracao", json=cfg | {"atrasoCriticoDias": 60})
    lista = client.get(f"{API}/pendencias").json()
    assert next(p for p in lista if p["titulo"].startswith("Aluguel em atraso"))["gravidade"] == "atencao"


def test_modelos_e_permissoes(client):
    modelos = client.get(f"{API}/modelos").json()
    assert modelos[0]["padrao"] is True and len(modelos[0]["itens"]) > 20
    uid = novo_id()
    client.put(f"/api/v1/equipe/usuarios/{uid}", json={
        "nome": "Fin", "login": "fin", "perfil": "financeiro",
        "permissoes": permissoes_do_perfil(PerfilAcesso.financeiro), "senha": "senha-forte-123"})  # fmt: skip
    token = client.post("/api/v1/auth/entrar", json={"usuario": "fin", "senha": "senha-forte-123"}).json()["token"]
    assert client.get(f"{API}/pendencias", headers={"Authorization": f"Bearer {token}"}).status_code == 403


# ------------------------------------------------------- Área do proprietário


def _entrar_proprietario(client, dono, cpf):
    senha = client.post(f"{API}/proprietarios/{dono}/acesso").json()["senha"]
    client.post("/proprietario/entrar", data={"documento": cpf, "senha": senha})
    csrf = re.search(r'name="csrf" value="([^"]+)"', client.get("/proprietario/senha").text).group(1)
    r = client.post("/proprietario/senha", data={"atual": senha, "nova": "senha-do-dono-1",
                                                 "repetida": "senha-do-dono-1", "csrf": csrf},
                    follow_redirects=False)  # fmt: skip
    assert r.headers["location"].startswith("/proprietario?ok="), r.headers


def test_area_do_proprietario(client):
    hoje = agora().date()
    dono, inquilino, im, cid = _cenario(client, pix="roberto@pix.com")
    paga = _cobranca(client, cid, f"{hoje.year}-02-01", f"{hoje.year}-02-10", status="paga",
                     dataPagamento=f"{hoje.year}-02-09", valorPago=3000)  # fmt: skip
    client.put(f"{LOC}/repasses/{paga}/{dono}", json={"data": f"{hoje.year}-02-12"})
    assert client.post(f"{API}/proprietarios/{inquilino}/acesso").json()["detail"].startswith("Cadastre o CPF")

    a = _auditoria(client, im, cid)
    for i in a["itens"]:
        i["estado"] = "ok"
    client.put(f"{API}/{a['id']}", json={"imovelId": im, "contratoId": cid, "itens": a["itens"], "nota": 5})
    ref = _upload(client, "tour.mp4", MP4, "video")
    vid = novo_id()
    client.put(f"{API}/{a['id']}/midias/{vid}", json={"referencia": ref, "tipo": "video", "titulo": "Tour"})
    client.post(f"{API}/{a['id']}/concluir", json={"publicar": False})

    _entrar_proprietario(client, dono, "529.982.247-25")
    painel = client.get("/proprietario")
    assert painel.status_code == 200 and painel.headers["cache-control"] == "no-store"
    assert "R$ 2.700" in painel.text  # 3.000 − 10% de taxa de administração
    repasses = client.get("/proprietario/repasses").text
    assert "R$ 300" in repasses and f"Repassado 12/02/{hoje.year}" in repasses

    # Não publicada: invisível (lista, relatório e mídia).
    assert a["numero"] not in client.get("/proprietario/auditorias").text
    assert client.get(f"/proprietario/auditorias/{a['id']}").status_code == 404
    assert client.get(f"/proprietario/midia/{vid}").status_code == 404
    client.post(f"{API}/{a['id']}/publicacao", json={"publicada": True})
    assert a["numero"] in client.get("/proprietario/auditorias").text
    rel = client.get(f"/proprietario/auditorias/{a['id']}").text
    assert "RELATÓRIO DE AUDITORIA" in rel and f"/proprietario/midia/{vid}" in rel
    assert client.get(f"/proprietario/midia/{vid}").content == MP4

    # A sessão do proprietário não vale no portal do inquilino.
    assert client.get("/inquilino", follow_redirects=False).headers["location"] == "/inquilino/entrar"

    # Outro proprietário não vê nada disso.
    client.cookies.clear()
    outro, *_ = _cenario(client, cpf_dono="111.444.777-35")
    _entrar_proprietario(client, outro, "111.444.777-35")
    assert client.get(f"/proprietario/auditorias/{a['id']}").status_code == 404
    assert client.get(f"/proprietario/midia/{vid}").status_code == 404


def test_imposto_retido_quando_inquilino_e_pj(banco):
    assert prop.imposto_mensal(2000, 2026) == 0
    assert prop.imposto_mensal(8000, 2026) == round(8000 * 0.275 - 908.73, 2)
    assert prop.imposto_mensal(8000, 2025) == round(8000 * 0.275 - 908.73, 2)
    assert prop.imposto_mensal(6000, 2026) < prop.imposto_mensal(6000, 2025)
    with banco() as db:
        assert db.scalar(sa.select(sa.func.count()).select_from(MidiaAuditoria)) == 0

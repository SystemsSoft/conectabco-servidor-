"""Vídeos tutoriais do site: link assinado do S3 ou arquivo do disco."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.central import tutoriais
from app.core.config import get_settings
from app.main import create_app
from tests.central.test_painel import _entrar, _nova, painel  # noqa: F401 - fixture

CAMINHO = "/associacao/tutoriais/como-contratar-o-sistema.mp4"


def test_no_disco(plataforma):
    with TestClient(create_app()) as c:
        assert c.get(CAMINHO).status_code == 404  # ainda não enviado
        arquivo = Path(get_settings().arquivos_dir) / tutoriais.TUTORIAIS["como-contratar-o-sistema"]
        arquivo.parent.mkdir(parents=True)
        arquivo.write_bytes(b"\x00\x00\x00\x18ftypmp42")
        r = c.get(CAMINHO)
        assert r.status_code == 200 and r.headers["content-type"] == "video/mp4"
        assert c.get("/associacao/tutoriais/outro.mp4").status_code == 404


def test_no_s3_redireciona_para_link_assinado(plataforma, monkeypatch):
    pedidos = []

    class S3Falso:
        def existe(self, chave):
            return True

        def link(self, chave, tipo, nome, inline, cache):
            pedidos.append((chave, tipo, inline))
            return "https://associacao-conecta.s3.amazonaws.com/assinado"

    monkeypatch.setattr(tutoriais, "armazenamento", S3Falso)
    with TestClient(create_app()) as c:
        r = c.get(CAMINHO, follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "https://associacao-conecta.s3.amazonaws.com/assinado"
    assert "max-age=3600" in r.headers["cache-control"]
    assert pedidos == [("plataforma/tutoriais/como-contratar-o-sistema.mp4", "video/mp4", True)]


def _video_no_disco(chave):
    arquivo = Path(get_settings().arquivos_dir) / chave
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_bytes(b"\x00\x00\x00\x18ftypmp42")


def test_tutorial_do_representante_so_com_login(painel):  # noqa: F811
    from tests.central.test_representantes import _cadastrar_representante, _entrar_representante

    for caminho in ("/representante/tutorial", "/representante/tutorial.mp4"):
        r = painel.get(caminho, follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/representante/entrar"
    _cadastrar_representante(painel, _entrar(painel))
    _entrar_representante(painel)
    assert 'href="/representante/tutorial">Tutorial' in painel.get("/representante").text
    assert "Assistir ao tutorial" in painel.get("/representante").text
    # Antes do envio: aviso no lugar do player, e o vídeo dá 404 (em vez de um link do S3 que não toca).
    pagina = painel.get("/representante/tutorial").text
    assert "estará disponível em breve" in pagina and "<video" not in pagina
    assert painel.get("/representante/tutorial.mp4").status_code == 404
    _video_no_disco(tutoriais.REPRESENTANTE)
    pagina = painel.get("/representante/tutorial").text
    assert 'src="/representante/tutorial.mp4"' in pagina and "Contrato: gerar link ou anexar" in pagina
    assert 'data-tempo="112"' in pagina and ">1:52</span>" in pagina and "disponível em breve" not in pagina
    assert painel.get("/representante/tutorial.mp4").headers["content-type"] == "video/mp4"


def test_tutorial_da_plataforma_so_com_login(painel):  # noqa: F811
    for caminho in ("/plataforma/tutorial", "/plataforma/tutorial.mp4"):
        assert painel.get(caminho, follow_redirects=False).status_code in (303, 401)
    _entrar(painel)
    assert 'href="/plataforma/tutorial"' in painel.get("/plataforma").text
    pagina = painel.get("/plataforma/tutorial").text
    assert "enviar_tutorial.sh tutorial/fluxo-de-implantacao-no-painel.mp4" in pagina and "<video" not in pagina
    assert painel.get("/plataforma/tutorial.mp4").status_code == 404  # ainda não enviado
    _video_no_disco(tutoriais.PLATAFORMA)
    pagina = painel.get("/plataforma/tutorial").text
    assert 'src="/plataforma/tutorial.mp4"' in pagina and "Confirmar o 1º pagamento" in pagina
    assert painel.get("/plataforma/tutorial.mp4").headers["content-type"] == "video/mp4"


def test_tutorial_nao_pode_ser_slug(painel):  # noqa: F811
    r = _nova(painel, _entrar(painel), slug="tutorial")
    assert r.status_code == 422

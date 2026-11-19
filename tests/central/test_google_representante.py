"""Login com Google na área do representante: depois do 1º acesso com usuário
e senha, ele conecta a conta Google em "Minha conta" e passa a entrar com ela.
Os ID tokens do Firebase são assinados aqui com uma chave RSA de teste."""

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.central import google
from app.core.config import get_settings
from tests.central.test_painel import _csrf, _entrar, painel  # noqa: F401 - fixture
from tests.central.test_representantes import REP, _cadastrar_representante, _entrar_representante

CHAVE = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PROJETO = "associacaoconectabrasil"


@pytest.fixture(autouse=True)
def chaves_de_teste(monkeypatch):
    monkeypatch.setattr(get_settings(), "firebase_project_id", PROJETO)
    monkeypatch.setattr(google, "_chave_publica", lambda token: CHAVE.public_key())


def _token(uid="google-uid-1", email="carlos@gmail.com", provedor="google.com", chave=CHAVE, **extra):
    agora = int(time.time())
    dados = {"iss": f"https://securetoken.google.com/{PROJETO}", "aud": PROJETO, "sub": uid,
             "iat": agora, "exp": agora + 3600, "auth_time": agora, "email": email,
             "firebase": {"sign_in_provider": provedor}} | extra  # fmt: skip
    return jwt.encode(dados, chave, algorithm="RS256", headers={"kid": "teste"})


def _sair(c):
    c.cookies.delete("representante", path="/representante")


def test_conectar_entrar_e_desconectar_google(painel):  # noqa: F811
    _cadastrar_representante(painel, _entrar(painel))

    # Antes de conectar: a conta Google não abre a área.
    entrada = painel.get("/representante/entrar").text
    assert "Entrar com Google" in entrada and "firebase-auth.js" in entrada and PROJETO in entrada
    r = painel.post("/representante/entrar/google", data={"id_token": _token()})
    assert r.status_code == 422 and "não está conectada" in r.text

    # Conectar em "Minha conta" (com CSRF e um token válido).
    csrf = _entrar_representante(painel)
    conta = painel.get("/representante/conta").text
    assert "Conectar conta Google" in conta and 'href="/representante/conta"' in conta
    assert painel.post("/representante/conta/google", data={"id_token": _token()}).status_code == 403
    r = painel.post("/representante/conta/google", data={"csrf": csrf, "id_token": "lixo"})
    assert r.status_code == 422 and "Não foi possível confirmar" in r.text
    r = painel.post("/representante/conta/google", data={"csrf": csrf, "id_token": _token()})
    assert r.headers["location"] == "/representante/conta?msg=google-conectado"
    conta = painel.get("/representante/conta").text
    assert "Conectada" in conta and "carlos@gmail.com" in conta and "Desconectar" in conta

    # Próximo acesso: só com o Google.
    _sair(painel)
    r = painel.post("/representante/entrar/google", data={"id_token": _token()})
    assert r.status_code == 303 and r.headers["location"] == "/representante"
    assert painel.get("/representante").status_code == 200

    # Desconectar: o Google deixa de entrar; usuário e senha continuam.
    csrf = _csrf(painel.get("/representante/conta").text)
    r = painel.post("/representante/conta/google/desconectar", data={"csrf": csrf})
    assert r.headers["location"] == "/representante/conta?msg=google-desconectado"
    _sair(painel)
    assert painel.post("/representante/entrar/google", data={"id_token": _token()}).status_code == 422
    _entrar_representante(painel)


def test_tokens_invalidos_sao_recusados(painel):  # noqa: F811
    _cadastrar_representante(painel, _entrar(painel))
    csrf = _entrar_representante(painel)
    painel.post("/representante/conta/google", data={"csrf": csrf, "id_token": _token()})
    _sair(painel)

    outra = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    agora = int(time.time())
    for token in (
        _token(chave=outra),  # assinatura de outra chave
        _token(aud="outro-projeto"),
        _token(iss="https://securetoken.google.com/outro-projeto"),
        _token(exp=agora - 3600, iat=agora - 7200),  # vencido
        _token(provedor="password"),  # login do Firebase que não é Google
        "",
    ):
        r = painel.post("/representante/entrar/google", data={"id_token": token})
        assert r.status_code == 422, token
    assert painel.get("/representante").headers["location"] == "/representante/entrar"


def test_conta_google_de_um_so_representante_e_desativado_nao_entra(painel):  # noqa: F811
    csrf_admin = _entrar(painel)
    _cadastrar_representante(painel, csrf_admin)
    _cadastrar_representante(painel, csrf_admin, nome="Ana Reis", login="ana.rep", senha="senha-da-ana-1")
    csrf = _entrar_representante(painel)
    painel.post("/representante/conta/google", data={"csrf": csrf, "id_token": _token()})

    # A mesma conta Google não conecta em outro representante.
    _sair(painel)
    csrf = _entrar_representante(painel, login="ana.rep", senha="senha-da-ana-1")
    r = painel.post("/representante/conta/google", data={"csrf": csrf, "id_token": _token()})
    assert r.status_code == 422 and "outro representante" in r.text

    # Desativado no painel: o Google também não entra.
    csrf_admin = _entrar(painel)
    lista = painel.get("/plataforma/representantes").text
    rid = lista.split("carlos.rep")[0].rsplit("/plataforma/representantes/", 1)[1].split('"')[0]
    dados = {"csrf": csrf_admin, "nome": "Carlos Souza", "login": REP["login"], "email": "carlos@exemplo.com",
             "telefone": "(21) 97777-6666", "regiao": ""}  # fmt: skip
    painel.post(f"/plataforma/representantes/{rid}", data=dados)
    r = painel.post("/representante/entrar/google", data={"id_token": _token()})
    assert r.status_code == 422 and "desativado" in r.text


def test_sem_firebase_o_botao_some(painel, monkeypatch):  # noqa: F811
    monkeypatch.setattr(get_settings(), "firebase_api_key", "")
    assert "Entrar com Google" not in painel.get("/representante/entrar").text

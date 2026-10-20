from datetime import timedelta

import sqlalchemy as sa

from app.core.tempo import agora
from app.modules.equipe.enums import PerfilAcesso, permissoes_do_perfil
from tests.apoio import novo_id
from tests.conftest import ADMIN

AUTH = "/api/v1/auth"
EQ = "/api/v1/equipe"


def _usuario(client, perfil="corretor", login="corretor", **extra):
    id = novo_id()
    r = client.put(f"{EQ}/usuarios/{id}", json={
        "nome": "Carlos Corretor", "login": login, "perfil": perfil,
        "permissoes": permissoes_do_perfil(PerfilAcesso(perfil)),
        "senha": "senha-do-corretor", **extra,
    })  # fmt: skip
    assert r.status_code == 201, r.text
    return id


def _entrar(cliente, usuario, senha="senha-do-corretor"):
    r = cliente.post(f"{AUTH}/entrar", json={"usuario": usuario, "senha": senha})
    return r


def _com_token(cliente, token):
    return {"Authorization": f"Bearer {token}"}


def test_login_e_rotas_protegidas(cliente_anonimo):
    assert cliente_anonimo.get("/api/v1/crm/imoveis").status_code == 401
    r = _entrar(cliente_anonimo, ADMIN["usuario"], "errada")
    assert r.json()["detail"] == "Usuário ou senha incorretos."
    r = _entrar(cliente_anonimo, "admin", ADMIN["senha"])  # sem diferenciar caixa
    assert r.status_code == 200
    h = _com_token(cliente_anonimo, r.json()["token"])
    assert cliente_anonimo.get("/api/v1/crm/imoveis", headers=h).status_code == 200
    assert cliente_anonimo.get(f"{AUTH}/eu", headers=h).json()["perfil"] == "administrador"
    assert cliente_anonimo.get("/saude").status_code == 200

    # Sair encerra a sessão: o mesmo token deixa de valer.
    assert cliente_anonimo.post(f"{AUTH}/sair", headers=h).status_code == 204
    r = cliente_anonimo.get("/api/v1/crm/imoveis", headers=h)
    assert (r.status_code, r.json()["detail"]) == (401, "Sua sessão foi encerrada. Entre novamente.")


def test_login_ignora_espacos_colados_nas_pontas(cliente_anonimo):
    # Copiar e colar costuma trazer espaço, quebra de linha, tabulação,
    # espaço sem quebra e espaço de largura zero.
    sujeiras = [" ", "\n", "\t", "\u00a0", "\u200b", "\ufeff", " \r\n"]
    for x in sujeiras:
        r = _entrar(cliente_anonimo, f"{x}{ADMIN['usuario']}{x}", f"{x}{ADMIN['senha']}{x}")
        assert r.status_code == 200, (repr(x), r.text)
    # Espaço no meio continua contando.
    meio = ADMIN["senha"][:4] + " " + ADMIN["senha"][4:]
    assert _entrar(cliente_anonimo, ADMIN["usuario"], meio).status_code != 200


def test_permissoes_por_modulo(client):
    _usuario(client)
    r = _entrar(client, "corretor")
    h = _com_token(client, r.json()["token"])
    assert client.get("/api/v1/crm/contatos", headers=h).status_code == 200
    r = client.get("/api/v1/financeiro/lancamentos", headers=h)
    assert (r.status_code, r.json()["detail"]) == (
        403, "Você não tem permissão para ver em Financeiro.")
    # Corretor cria e edita no CRM, mas não exclui.
    cid = novo_id()
    assert client.put(f"/api/v1/crm/contatos/{cid}", headers=h,
                      json={"nome": "Cliente"}).status_code == 201  # fmt: skip
    r = client.delete(f"/api/v1/crm/contatos/{cid}", headers=h)
    assert r.json()["detail"] == "Você não tem permissão para excluir em Cadastros e CRM."
    # Não gerencia usuários.
    r = client.put(f"{EQ}/configuracao", headers=h,
                   json={"limiteSessoes": 2, "inatividadeMinutos": 30})  # fmt: skip
    assert r.status_code == 403


def test_limite_de_sessoes_e_inatividade(client, banco):
    client.put(f"{EQ}/configuracao", json={"limiteSessoes": 1, "inatividadeMinutos": 30})
    _usuario(client)
    r = _entrar(client, "corretor")
    assert r.json()["detail"].startswith("Limite de 1 usuário(s) simultâneo(s)")
    # O próprio admin pode abrir outra sessão.
    assert _entrar(client, ADMIN["usuario"], ADMIN["senha"]).status_code == 200

    # Sessões paradas além do limite expiram.
    from app.modules.equipe.models import Sessao

    with banco() as db:
        db.execute(sa.update(Sessao).values(ultima_atividade=agora() - timedelta(hours=1)))
        db.commit()
    r = client.get("/api/v1/crm/imoveis")
    assert r.json()["detail"] == "Sua sessão expirou por inatividade. Entre novamente."
    assert _entrar(client, "corretor").status_code == 200


def test_usuarios_regras(client):
    eu = client.get(f"{AUTH}/eu").json()
    uid = _usuario(client)
    dados = {"nome": "Carlos", "login": "corretor", "perfil": "corretor",
             "permissoes": permissoes_do_perfil(PerfilAcesso.corretor)}  # fmt: skip
    # E-mail repetido, senha curta, novo sem senha.
    r = client.put(f"{EQ}/usuarios/{novo_id()}", json=dados | {"login": "CORRETOR", "senha": "12345678"})
    assert r.json()["detail"] == "Já existe outro usuário com este login."
    r = client.put(f"{EQ}/usuarios/{novo_id()}", json=dados | {"login": "com espaço", "senha": "12345678"})
    assert r.json()["detail"].startswith("Usuário inválido")
    r = client.put(f"{EQ}/usuarios/{novo_id()}", json=dados | {"login": "outro", "email": "x@", "senha": "12345678"})
    assert r.json()["detail"] == "E-mail inválido."
    r = client.put(f"{EQ}/usuarios/{uid}", json=dados | {"senha": "curta"})
    assert r.json()["detail"] == "A senha precisa de ao menos 8 caracteres."
    r = client.put(f"{EQ}/usuarios/{novo_id()}", json=dados | {"login": "novo"})
    assert r.json()["detail"] == "Defina uma senha para o novo usuário."
    # Senha nunca sai na API.
    assert "senha" not in str(client.get(f"{EQ}/usuarios").json()).lower().replace("senhaHash", "")

    # Não se exclui, não fica sem administrador.
    assert client.delete(f"{EQ}/usuarios/{eu['id']}").json()["detail"] == (
        "Você não pode excluir o usuário que está em uso.")
    r = client.put(f"{EQ}/usuarios/{eu['id']}", json={
        "nome": eu["nome"], "login": eu["login"], "perfil": "administrador",
        "permissoes": eu["permissoes"], "ativo": False})  # fmt: skip
    assert r.json()["detail"] == "Mantenha ao menos um administrador ativo."

    # Desativar encerra as sessões do usuário.
    h = _com_token(client, _entrar(client, "corretor").json()["token"])
    client.put(f"{EQ}/usuarios/{uid}", json=dados | {"ativo": False})
    assert client.get("/api/v1/crm/imoveis", headers=h).status_code == 401
    assert _entrar(client, "corretor").json()["detail"] == (
        "Este usuário está desativado.")
    assert client.delete(f"{EQ}/usuarios/{uid}").status_code == 204


def test_alterar_senha(client):
    r = client.post(f"{AUTH}/alterar-senha", json={"senhaAtual": "x", "novaSenha": "nova-senha-1"})
    assert r.json()["detail"] == "A senha atual não confere."
    r = client.post(f"{AUTH}/alterar-senha",
                    json={"senhaAtual": ADMIN["senha"], "novaSenha": "nova-senha-1"})  # fmt: skip
    assert r.status_code == 204
    assert _entrar(client, ADMIN["usuario"], "nova-senha-1").status_code == 200


def test_chat_privado_e_comissoes_proprias(client):
    eu = client.get(f"{AUTH}/eu").json()["id"]
    outro = _usuario(client)
    terceiro = _usuario(client, login="terceiro")
    dm = f"dm:{min(eu, outro)}:{max(eu, outro)}"
    msg = {"conversaId": dm, "remetenteId": eu, "texto": "Oi", "enviadaEm": "2026-10-15T10:00:00"}
    assert client.put(f"{EQ}/mensagens/{novo_id()}", json=msg).status_code == 200
    # Terceiro não vê a conversa direta.
    h3 = _com_token(client, _entrar(client, "terceiro").json()["token"])
    assert client.get(f"{EQ}/mensagens", headers=h3).json() == []
    assert len(client.get(f"{EQ}/mensagens").json()) == 1

    # Comissões: corretor sem "ver de todos" só recebe as próprias.
    for uid in (outro, terceiro):
        client.put(f"{EQ}/comissoes/{novo_id()}", json={
            "usuarioId": uid, "tipo": "venda", "competencia": "2026-10-15", "valor": 1000})  # fmt: skip
    proprias = client.get(f"{EQ}/comissoes", headers=h3).json()
    assert [c["usuarioId"] for c in proprias] == [terceiro]
    assert proprias[0]["competencia"] == "2026-10-01"
    assert len(client.get(f"{EQ}/comissoes").json()) == 2


def test_fila_e_atividades(client):
    eu = client.get(f"{AUTH}/eu").json()["id"]
    fila = [{"usuarioId": eu, "status": "disponivel", "desde": "2026-10-15T09:00:00"}]
    assert client.put(f"{EQ}/fila", json=fila).json() == fila
    assert client.put(f"{EQ}/fila", json=fila * 2).status_code == 422
    client.put(f"{EQ}/atividades/{novo_id()}", json={"tipo": "edicao", "descricao": "Teste"})
    tipos = [a["tipo"] for a in client.get(f"{EQ}/atividades").json()]
    assert "login" in tipos and "edicao" in tipos


def test_resumo_do_dispositivo():
    from app.modules.equipe.services import resumir_dispositivo

    mac_chrome = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/152.0 Safari/537.36")  # fmt: skip
    assert resumir_dispositivo(mac_chrome) == "Chrome no macOS"
    win_edge = "Mozilla/5.0 (Windows NT 10.0) Chrome/150 Safari/537.36 Edg/150"
    assert resumir_dispositivo(win_edge) == "Edge no Windows"
    assert resumir_dispositivo("") == "Navegador"


def test_corretor_usa_chat_e_fila_e_ve_quem_esta_online(client):
    eu = client.get(f"{AUTH}/eu").json()["id"]
    _usuario(client)
    h = _com_token(client, _entrar(client, "corretor").json()["token"])
    online = client.get(f"{EQ}/sessoes", headers=h).json()
    assert {x["usuarioId"] for x in online} >= {eu}
    assert all(x["dispositivo"] == "" for x in online)
    assert any(x["dispositivo"] for x in client.get(f"{EQ}/sessoes").json())
    # Fila e chat liberados; histórico de atividades, não.
    assert client.get(f"{EQ}/fila", headers=h).status_code == 200
    assert client.get(f"{EQ}/mensagens", headers=h).status_code == 200
    assert client.get(f"{EQ}/atividades", headers=h).status_code == 403

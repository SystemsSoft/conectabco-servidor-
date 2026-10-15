from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.orm import Session

from app.core.auth import UsuarioLogado, exigir_especial, exigir_modulo
from app.core.database import get_db
from app.core.errors import NaoEncontrado, RegraNegocio, validar_id
from app.core.seguranca import ler_token
from app.core.tempo import agora
from app.modules.equipe import models as m
from app.modules.equipe import schemas as s
from app.modules.equipe import services as svc
from app.modules.equipe.enums import ModuloSistema, StatusComissao

Db = Annotated[Session, Depends(get_db)]
_GERENCIAR = "Só quem pode gerenciar usuários faz esta alteração."


def _criado(response: Response, criado: bool) -> None:
    if criado:
        response.status_code = status.HTTP_201_CREATED


# ===================================================================== Login

auth = APIRouter(prefix="/auth", tags=["Login"])


@auth.post("/entrar", response_model=s.LoginSaida)
def entrar(dados: s.Login, db: Db, request: Request):
    """Confere e-mail e senha, abre a sessão (respeitando o limite de usuários
    simultâneos) e devolve o token para o cabeçalho Authorization: Bearer."""
    return svc.entrar(db, dados, request.headers.get("user-agent", ""))


@auth.post("/sair", status_code=204)
def sair(db: Db, usuario: UsuarioLogado, request: Request) -> None:
    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    svc.sair(db, usuario, (ler_token(token) or {}).get("sid"))


@auth.get("/eu", response_model=s.UsuarioSaida)
def eu(usuario: UsuarioLogado):
    return svc.usuario_saida(usuario)


@auth.post("/alterar-senha", status_code=204)
def alterar_senha(dados: s.AlterarSenha, db: Db, usuario: UsuarioLogado) -> None:
    svc.alterar_senha(db, usuario, dados)


# ==================================================================== Equipe

router = APIRouter(prefix="/equipe")
_t = ["Equipe • Usuários e sessões"]


@router.get("/usuarios", tags=_t, response_model=list[s.UsuarioSaida])
def listar_usuarios(db: Db, _: UsuarioLogado):
    """Todos os usuários logados veem a equipe (chat, fila, avatares)."""
    return [svc.usuario_saida(u) for u in db.scalars(sa.select(m.Usuario).order_by(m.Usuario.nome))]


@router.put("/usuarios/{id}", tags=_t, response_model=s.UsuarioSaida)
def salvar_usuario(id: str, dados: s.UsuarioEntrada, db: Db, usuario: UsuarioLogado,
                   response: Response):  # fmt: skip
    exigir_especial(usuario, "gerenciarUsuarios", _GERENCIAR)
    salvo, criado = svc.salvar_usuario(db, id, dados, usuario)
    _criado(response, criado)
    return salvo


@router.delete("/usuarios/{id}", tags=_t, status_code=204)
def remover_usuario(id: str, db: Db, usuario: UsuarioLogado) -> None:
    exigir_especial(usuario, "gerenciarUsuarios", _GERENCIAR)
    svc.remover_usuario(db, id, usuario)


@router.get("/sessoes", tags=_t, response_model=list[s.SessaoSaida],
            dependencies=[exigir_modulo("equipeSeguranca")])  # fmt: skip
def listar_sessoes(db: Db):
    return [s.SessaoSaida.model_validate(x) for x in svc.sessoes_ativas(db)]


@router.delete("/sessoes/{id}", tags=_t, status_code=204)
def encerrar_sessao(id: str, db: Db, usuario: UsuarioLogado) -> None:
    sessao = db.get(m.Sessao, id)
    if sessao is None:
        return
    if sessao.usuario_id != usuario.id:
        exigir_especial(usuario, "gerenciarUsuarios", _GERENCIAR)
    alvo = db.get(m.Usuario, sessao.usuario_id)
    db.delete(sessao)
    svc.registrar(db, usuario.id, svc.TipoAtividade.logout,
                  f"Sessão de {alvo.nome if alvo else 'usuário'} encerrada",
                  ModuloSistema.equipeSeguranca)  # fmt: skip
    db.commit()


@router.get("/configuracao", tags=_t, response_model=s.ConfiguracaoSeguranca)
def obter_configuracao(db: Db, _: UsuarioLogado):
    return s.ConfiguracaoSeguranca.model_validate(svc.configuracao(db))


@router.put("/configuracao", tags=_t, response_model=s.ConfiguracaoSeguranca)
def salvar_configuracao(dados: s.ConfiguracaoSeguranca, db: Db, usuario: UsuarioLogado):
    exigir_especial(usuario, "gerenciarUsuarios", _GERENCIAR)
    if not 1 <= dados.limite_sessoes <= 100:
        raise RegraNegocio("O limite deve ser de 1 a 100 usuários.")
    if not 5 <= dados.inatividade_minutos <= 480:
        raise RegraNegocio("A inatividade deve ser de 5 a 480 minutos.")
    cfg = db.get(m.ConfiguracaoSeguranca, 1)
    if cfg is None:
        cfg = m.ConfiguracaoSeguranca(id=1)
        db.add(cfg)
    cfg.limite_sessoes = dados.limite_sessoes
    cfg.inatividade_minutos = dados.inatividade_minutos
    svc.registrar(db, usuario.id, svc.TipoAtividade.permissao,
                  f"Alterou a segurança: {dados.limite_sessoes} simultâneos, "
                  f"{dados.inatividade_minutos} min de inatividade",
                  ModuloSistema.equipeSeguranca)  # fmt: skip
    db.commit()
    return s.ConfiguracaoSeguranca.model_validate(cfg)


# ---------------------------------------------------------------- Atividades
_t = ["Equipe • Atividades"]


@router.get("/atividades", tags=_t, response_model=list[s.AtividadeSaida],
            dependencies=[exigir_modulo("equipeSeguranca")])  # fmt: skip
def listar_atividades(db: Db, limite: int = 1000):
    q = sa.select(m.Atividade).order_by(m.Atividade.quando.desc()).limit(min(limite, 5000))
    return [s.AtividadeSaida.model_validate(a) for a in db.scalars(q)]


@router.put("/atividades/{id}", tags=_t, response_model=s.AtividadeSaida)
def registrar_atividade(id: str, dados: s.AtividadeEntrada, db: Db, usuario: UsuarioLogado):
    """Registra uma ação do usuário logado (o autor vem do token)."""
    a = db.get(m.Atividade, validar_id(id))
    if a is None:
        a = m.Atividade(id=id, usuario_id=usuario.id, quando=agora(),
                        tipo=dados.tipo, descricao=dados.descricao, modulo=dados.modulo)  # fmt: skip
        db.add(a)
        db.commit()
    return s.AtividadeSaida.model_validate(a)


# ---------------------------------------------------- Fila e atendimentos
_t = ["Equipe • Fila de atendimento"]


@router.get("/fila", tags=_t, response_model=list[s.ItemFila])
def listar_fila(db: Db, _: UsuarioLogado):
    q = sa.select(m.ItemFila).order_by(m.ItemFila.posicao)
    return [s.ItemFila.model_validate(i) for i in db.scalars(q)]


@router.put("/fila", tags=_t, response_model=list[s.ItemFila])
def salvar_fila(fila: list[s.ItemFila], db: Db, _: UsuarioLogado):
    """Substitui a fila inteira, na ordem recebida."""
    ids = [i.usuario_id for i in fila]
    if len(set(ids)) != len(ids):
        raise RegraNegocio("Um corretor aparece duas vezes na fila.")
    for uid in ids:
        if db.get(m.Usuario, uid) is None:
            raise RegraNegocio("Usuário da fila não encontrado.")
    db.execute(sa.delete(m.ItemFila))
    for pos, i in enumerate(fila):
        db.add(m.ItemFila(usuario_id=i.usuario_id, posicao=pos, status=i.status, desde=i.desde))
    db.commit()
    return fila


@router.get("/atendimentos", tags=_t, response_model=list[s.AtendimentoSaida])
def listar_atendimentos(db: Db, _: UsuarioLogado):
    q = sa.select(m.Atendimento).order_by(m.Atendimento.iniciado_em.desc())
    return [s.AtendimentoSaida.model_validate(a) for a in db.scalars(q)]


@router.put("/atendimentos/{id}", tags=_t, response_model=s.AtendimentoSaida)
def salvar_atendimento(id: str, dados: s.Atendimento, db: Db, _: UsuarioLogado,
                       response: Response):  # fmt: skip
    if db.get(m.Usuario, dados.corretor_id) is None:
        raise RegraNegocio("Corretor não encontrado.")
    if not dados.cliente_nome.strip():
        raise RegraNegocio("Informe o nome do cliente.")
    a = db.get(m.Atendimento, validar_id(id))
    criado = a is None
    if criado:
        a = m.Atendimento(id=id)
        db.add(a)
    for campo, valor in dados.model_dump().items():
        setattr(a, campo, valor)
    db.commit()
    _criado(response, criado)
    return s.AtendimentoSaida.model_validate(a)


# ----------------------------------------------------------------- Comissões
_t = ["Equipe • Comissões"]


@router.get("/comissoes/regras", tags=_t, response_model=list[s.RegraComissaoSaida])
def listar_regras(db: Db, _: UsuarioLogado):
    return [s.RegraComissaoSaida.model_validate(r) for r in db.scalars(sa.select(m.RegraComissao))]


@router.put("/comissoes/regras/{usuario_id}", tags=_t, response_model=s.RegraComissaoSaida,
            dependencies=[exigir_modulo("equipeSeguranca")])  # fmt: skip
def salvar_regra(usuario_id: str, dados: s.RegraComissao, db: Db):
    if db.get(m.Usuario, usuario_id) is None:
        raise NaoEncontrado("Usuário não encontrado.")
    for p in (dados.percentual_venda, dados.percentual_locacao, dados.percentual_captacao):
        if not 0 <= p <= 100:
            raise RegraNegocio("Os percentuais devem ficar entre 0 e 100%.")
    if dados.meta_mensal < 0:
        raise RegraNegocio("A meta não pode ser negativa.")
    r = db.get(m.RegraComissao, usuario_id) or m.RegraComissao(usuario_id=usuario_id)
    db.add(r)
    for campo, valor in dados.model_dump().items():
        setattr(r, campo, valor)
    db.commit()
    return s.RegraComissaoSaida.model_validate(r)


@router.get("/comissoes", tags=_t, response_model=list[s.LancamentoComissaoSaida])
def listar_comissoes(db: Db, usuario: UsuarioLogado):
    """Sem "ver comissões de todos", o usuário recebe só as próprias."""
    q = sa.select(m.LancamentoComissao).order_by(m.LancamentoComissao.competencia.desc())
    if not usuario.tem_especial("verComissoesDeTodos"):
        q = q.where(m.LancamentoComissao.usuario_id == usuario.id)
    return [s.LancamentoComissaoSaida.model_validate(x) for x in db.scalars(q)]


@router.put("/comissoes/{id}", tags=_t, response_model=s.LancamentoComissaoSaida,
            dependencies=[exigir_modulo("equipeSeguranca")])  # fmt: skip
def salvar_comissao(id: str, dados: s.LancamentoComissao, db: Db, response: Response):
    if db.get(m.Usuario, dados.usuario_id) is None:
        raise RegraNegocio("Corretor não encontrado.")
    if dados.valor <= 0:
        raise RegraNegocio("Informe o valor da comissão.")
    dados.competencia = dados.competencia.replace(day=1)
    if dados.status != StatusComissao.paga:
        dados.data_pagamento = None
    obj = db.get(m.LancamentoComissao, validar_id(id))
    criado = obj is None
    if criado:
        obj = m.LancamentoComissao(id=id)
        db.add(obj)
    for campo, valor in dados.model_dump().items():
        setattr(obj, campo, valor)
    db.commit()
    _criado(response, criado)
    return s.LancamentoComissaoSaida.model_validate(obj)


@router.delete("/comissoes/{id}", tags=_t, status_code=204,
               dependencies=[exigir_modulo("equipeSeguranca")])  # fmt: skip
def remover_comissao(id: str, db: Db) -> None:
    obj = db.get(m.LancamentoComissao, id)
    if obj is not None:
        if obj.status == StatusComissao.paga:
            raise RegraNegocio("Comissão paga não pode ser excluída.")
        db.delete(obj)
        db.commit()


# ---------------------------------------------------------------------- Chat
_t = ["Equipe • Chat interno"]


def _participa(conversa_id: str, usuario_id: str) -> bool:
    return conversa_id == "geral" or (
        conversa_id.startswith("dm:") and usuario_id in conversa_id.split(":")[1:]
    )


def _gravar_mensagem(db: Session, id: str, d: s.MensagemEntrada, usuario) -> m.Mensagem:
    if not _participa(d.conversa_id, usuario.id):
        raise RegraNegocio("Você não participa desta conversa.")
    msg = db.get(m.Mensagem, validar_id(id))
    if msg is None:
        if d.remetente_id != usuario.id:
            raise RegraNegocio("Envie mensagens só em seu nome.")
        if not d.texto.strip():
            raise RegraNegocio("Escreva a mensagem.")
        msg = m.Mensagem(id=id, conversa_id=d.conversa_id, remetente_id=usuario.id,
                         texto=d.texto.strip(), enviada_em=d.enviada_em)  # fmt: skip
        db.add(msg)
    # Em mensagens existentes, só a lista de leitura muda.
    msg.lida_por = sorted(set(msg.lida_por or []) | set(d.lida_por))
    return msg


@router.get("/mensagens", tags=_t, response_model=list[s.MensagemSaida])
def listar_mensagens(db: Db, usuario: UsuarioLogado):
    """Só as conversas de que o usuário participa (geral e as diretas dele)."""
    q = sa.select(m.Mensagem).where(
        sa.or_(m.Mensagem.conversa_id == "geral",
               m.Mensagem.conversa_id.like(f"dm:%{usuario.id}%"))  # fmt: skip
    ).order_by(m.Mensagem.enviada_em)
    return [s.MensagemSaida.model_validate(x) for x in db.scalars(q)
            if _participa(x.conversa_id, usuario.id)]  # fmt: skip


@router.put("/mensagens", tags=_t, response_model=list[s.MensagemSaida])
def salvar_mensagens(lote: list[s.MensagemLote], db: Db, usuario: UsuarioLogado):
    """Grava várias de uma vez (ex.: marcar a conversa como lida)."""
    msgs = [_gravar_mensagem(db, x.id, x, usuario) for x in lote]
    db.commit()
    return [s.MensagemSaida.model_validate(x) for x in msgs]


@router.put("/mensagens/{id}", tags=_t, response_model=s.MensagemSaida)
def salvar_mensagem(id: str, dados: s.MensagemEntrada, db: Db, usuario: UsuarioLogado):
    msg = _gravar_mensagem(db, id, dados, usuario)
    db.commit()
    return s.MensagemSaida.model_validate(msg)


@router.delete("/mensagens/{id}", tags=_t, status_code=204)
def apagar_mensagem(id: str, db: Db, usuario: UsuarioLogado) -> None:
    msg = db.get(m.Mensagem, id)
    if msg is None:
        return
    if msg.remetente_id != usuario.id:
        raise RegraNegocio("Só quem enviou pode apagar a mensagem.")
    db.delete(msg)
    db.commit()

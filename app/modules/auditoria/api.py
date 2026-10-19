"""Auditorias (app): pendências automáticas, auditorias em campo, visão por
proprietário, modelos de checklist e acesso do proprietário ao portal."""

from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import Field
from sqlalchemy.orm import Session

from app.core.auth import UsuarioLogado
from app.core.database import get_db
from app.core.errors import NaoEncontrado, validar_id
from app.core.schemas import Esquema, Pagina, pagina
from app.modules.auditoria import models as m
from app.modules.auditoria import pendencias as p
from app.modules.auditoria import relatorio
from app.modules.auditoria import schemas as s
from app.modules.auditoria import services as svc
from app.modules.auditoria.enums import StatusAuditoria
from app.modules.proprietario import services as proprietario

router = APIRouter(prefix="/auditorias", tags=["Auditorias"])
Db = Annotated[Session, Depends(get_db)]


class ManutencoesGeradas(Esquema):
    criadas: int
    auditoria: s.AuditoriaSaida


class LinkRelatorio(Esquema):
    link: str


class SenhaProvisoria(Esquema):
    login: str
    senha: str = Field(description="Mostrada uma única vez")


# ------------------------------------------------- Pendências automáticas


@router.get("/pendencias", response_model=list[s.Pendencia])
def pendencias(db: Db, proprietario_id: str | None = Query(None, alias="proprietarioId")):
    lista = p.pendencias(p.carregar(db, svc.configuracao(db)))
    return [x for x in lista if not proprietario_id or x.proprietario_id == proprietario_id]


@router.get("/proprietarios", response_model=list[s.ResumoProprietario])
def proprietarios(db: Db):
    dados = p.carregar(db, svc.configuracao(db))
    return p.proprietarios(dados, p.pendencias(dados), proprietario.acessos_por_contato(db))


@router.get("/configuracao", response_model=s.ConfiguracaoAuditoria)
def obter_configuracao(db: Db):
    return svc.configuracao(db)


@router.put("/configuracao", response_model=s.ConfiguracaoAuditoria)
def salvar_configuracao(dados: s.ConfiguracaoAuditoria, db: Db):
    return svc.salvar_configuracao(db, dados)


# ------------------------------------------------- Acesso do proprietário


@router.post("/proprietarios/{contato_id}/acesso", response_model=SenhaProvisoria)
def liberar_acesso(contato_id: str, db: Db):
    """Libera a Área do proprietário ou gera nova senha provisória."""
    acesso, senha = proprietario.liberar_acesso(db, validar_id(contato_id))
    return SenhaProvisoria(login=acesso.login, senha=senha)


@router.delete("/proprietarios/{contato_id}/acesso", status_code=204)
def revogar_acesso(contato_id: str, db: Db):
    proprietario.revogar_acesso(db, validar_id(contato_id))
    return Response(status_code=204)


# ------------------------------------------------------- Modelos


@router.get("/modelos", response_model=list[s.ModeloChecklistSaida])
def listar_modelos(db: Db):
    return [s.ModeloChecklistSaida.model_validate(x) for x in svc.modelos(db)]


@router.put("/modelos/{id}", response_model=s.ModeloChecklistSaida)
def salvar_modelo(id: str, dados: s.ModeloChecklist, db: Db):
    return s.ModeloChecklistSaida.model_validate(svc.salvar_modelo(db, id, dados))


@router.delete("/modelos/{id}", status_code=204)
def remover_modelo(id: str, db: Db):
    modelo = db.get(m.ModeloChecklist, validar_id(id))
    if modelo is None:
        raise NaoEncontrado("Modelo não encontrado.")
    db.delete(modelo)
    db.commit()
    return Response(status_code=204)


# ------------------------------------------------------- Auditorias


@router.get("", response_model=Pagina[s.AuditoriaSaida])
def listar(
    db: Db,
    status: StatusAuditoria | None = None,
    imovel_id: str | None = Query(None, alias="imovelId"),
    proprietario_id: str | None = Query(None, alias="proprietarioId"),
    limite: Annotated[int, Query(ge=1, le=500)] = 100,
    deslocamento: Annotated[int, Query(ge=0)] = 0,
):
    filtros = [
        f for f in (
            m.Auditoria.status == status if status else None,
            m.Auditoria.imovel_id == imovel_id if imovel_id else None,
            m.Auditoria.proprietario_id == proprietario_id if proprietario_id else None,
        ) if f is not None
    ]  # fmt: skip
    total = db.scalar(sa.select(sa.func.count()).select_from(m.Auditoria).where(*filtros))
    itens = db.scalars(
        sa.select(m.Auditoria).where(*filtros)
        .order_by(m.Auditoria.criado_em.desc(), m.Auditoria.id)
        .limit(limite).offset(deslocamento)
    ).all()  # fmt: skip
    return pagina([svc.saida(a) for a in itens], total, limite, deslocamento)


@router.get("/{id}", response_model=s.AuditoriaSaida)
def obter(id: str, db: Db):
    return svc.saida(svc.buscar(db, id))


@router.put("/{id}", response_model=s.AuditoriaSaida)
def salvar(id: str, dados: s.AuditoriaEntrada, db: Db, response: Response):
    a, nova = svc.salvar(db, id, dados)
    if nova:
        response.status_code = 201
    return svc.saida(a)


@router.delete("/{id}", status_code=204)
def remover(id: str, db: Db):
    svc.remover(db, id)
    return Response(status_code=204)


@router.post("/{id}/concluir", response_model=s.AuditoriaSaida)
def concluir(id: str, dados: s.Conclusao, db: Db, usuario: UsuarioLogado):
    return svc.saida(svc.concluir(db, id, dados.publicar, usuario.id))


@router.post("/{id}/reabrir", response_model=s.AuditoriaSaida)
def reabrir(id: str, db: Db, usuario: UsuarioLogado):
    """Desfaz a conclusão (exige poder excluir em Auditorias)."""
    if not usuario.pode("auditorias", "excluir"):
        raise HTTPException(403, "Só quem pode excluir auditorias pode reabri-las.")
    return svc.saida(svc.reabrir(db, id))


@router.post("/{id}/publicacao", response_model=s.AuditoriaSaida)
def publicacao(id: str, dados: s.Publicacao, db: Db):
    """Publica (ou retira) a auditoria concluída da Área do proprietário."""
    return svc.saida(svc.publicar(db, id, dados.publicada))


@router.post("/{id}/manutencoes", response_model=ManutencoesGeradas)
def gerar_manutencoes(id: str, db: Db):
    a, criadas = svc.gerar_manutencoes(db, id)
    return ManutencoesGeradas(criadas=criadas, auditoria=svc.saida(a))


@router.post("/{id}/relatorio", response_model=LinkRelatorio)
def link_relatorio(id: str, db: Db):
    """Link temporário (assinado) para abrir/imprimir o relatório."""
    return LinkRelatorio(link=relatorio.link(svc.buscar(db, id).id))


@router.put("/{id}/midias/{midia_id}", response_model=s.AuditoriaSaida)
def salvar_midia(id: str, midia_id: str, dados: s.MidiaEntrada, db: Db):
    return svc.saida(svc.salvar_midia(db, id, midia_id, dados))


@router.delete("/{id}/midias/{midia_id}", response_model=s.AuditoriaSaida)
def remover_midia(id: str, midia_id: str, db: Db):
    return svc.saida(svc.remover_midia(db, id, midia_id))


@router.post("/{id}/midias/{midia_id}/transcrever", response_model=s.AuditoriaSaida)
def transcrever(id: str, midia_id: str, db: Db):
    """Põe o vídeo na fila de transcrição do servidor."""
    return svc.saida(svc.pedir_transcricao(db, id, midia_id))

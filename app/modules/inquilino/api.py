"""Gestão do portal do inquilino (app): acessos, documentos do contrato e
comunicados. Permissão: Administração de Locação."""

from datetime import datetime
from typing import Annotated

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Query, Response
from pydantic import Field
from sqlalchemy.orm import Session

from app.core.auth import UsuarioLogado
from app.core.database import get_db
from app.core.errors import NaoEncontrado, RegraNegocio, validar_id
from app.core.schemas import Esquema
from app.core.tempo import agora
from app.modules.arquivos.models import Arquivo
from app.modules.inquilino import models as m
from app.modules.inquilino import services
from app.modules.inquilino.enums import OrigemArquivo, TipoArquivoContrato
from app.modules.locacao.models import ContratoLocacao

router = APIRouter(prefix="/portal-inquilino", tags=["Portal do inquilino"])
Db = Annotated[Session, Depends(get_db)]


class AcessoSaida(Esquema):
    contato_id: str
    login: str
    ativo: bool
    trocar_senha: bool
    bloqueado: bool
    ultimo_acesso: datetime | None
    criado_em: datetime


class SenhaProvisoria(Esquema):
    login: str
    senha: str = Field(description="Mostrada uma única vez")


class ArquivoContratoEntrada(Esquema):
    contrato_id: str
    tipo: TipoArquivoContrato
    titulo: Annotated[str, Field(max_length=200)]
    referencia: str = Field(description="arquivo:<id> devolvido pelo envio")
    observacao: str = ""
    visivel_inquilino: bool = True


class ArquivoContratoSaida(Esquema):
    id: str
    contrato_id: str
    manutencao_id: str | None
    tipo: TipoArquivoContrato
    origem: OrigemArquivo
    titulo: str
    observacao: str
    referencia: str
    visivel_inquilino: bool
    criado_em: datetime


class ComunicadoEntrada(Esquema):
    contrato_id: str | None = Field(None, description="Vazio = todos os inquilinos")
    titulo: Annotated[str, Field(max_length=200)]
    mensagem: Annotated[str, Field(max_length=5000)]


class ComunicadoSaida(Esquema):
    id: str
    contrato_id: str | None
    titulo: str
    mensagem: str
    automatico: bool
    criado_em: datetime
    leituras: int


def _acesso_saida(a: m.AcessoInquilino) -> AcessoSaida:
    return AcessoSaida(
        contato_id=a.contato_id, login=a.login, ativo=a.ativo, trocar_senha=a.trocar_senha,
        bloqueado=bool(a.bloqueado_ate and a.bloqueado_ate > agora()),
        ultimo_acesso=a.ultimo_acesso, criado_em=a.criado_em,
    )  # fmt: skip


def _arquivo_saida(a: m.ArquivoContrato) -> ArquivoContratoSaida:
    return ArquivoContratoSaida(
        id=a.id, contrato_id=a.contrato_id, manutencao_id=a.manutencao_id, tipo=a.tipo,
        origem=a.origem, titulo=a.titulo, observacao=a.observacao,
        referencia=f"arquivo:{a.arquivo_id}", visivel_inquilino=a.visivel_inquilino,
        criado_em=a.criado_em,
    )  # fmt: skip


# ------------------------------------------------------------------ Acessos


@router.get("/acessos", response_model=list[AcessoSaida])
def listar_acessos(db: Db):
    return [_acesso_saida(a) for a in db.scalars(sa.select(m.AcessoInquilino))]


@router.post("/acessos/{contato_id}", response_model=SenhaProvisoria)
def liberar_acesso(contato_id: str, db: Db):
    """Libera o acesso ou gera nova senha provisória (as sessões antigas caem)."""
    acesso, senha = services.liberar_acesso(db, validar_id(contato_id))
    return SenhaProvisoria(login=acesso.login, senha=senha)


@router.delete("/acessos/{contato_id}", status_code=204)
def revogar_acesso(contato_id: str, db: Db):
    services.revogar_acesso(db, validar_id(contato_id))
    return Response(status_code=204)


# --------------------------------------------------------------- Arquivos


@router.get("/arquivos", response_model=list[ArquivoContratoSaida])
def listar_arquivos(
    db: Db,
    contrato_id: str | None = Query(None, alias="contratoId"),
    manutencao_id: str | None = Query(None, alias="manutencaoId"),
):
    q = sa.select(m.ArquivoContrato).order_by(m.ArquivoContrato.criado_em.desc())
    if contrato_id:
        q = q.where(m.ArquivoContrato.contrato_id == contrato_id)
    if manutencao_id:
        q = q.where(m.ArquivoContrato.manutencao_id == manutencao_id)
    return [_arquivo_saida(a) for a in db.scalars(q)]


@router.put("/arquivos/{id}", response_model=ArquivoContratoSaida)
def salvar_arquivo(id: str, dados: ArquivoContratoEntrada, db: Db, response: Response):
    """Publica (ou edita) um documento da imobiliária no contrato."""
    id = validar_id(id)
    contrato = db.get(ContratoLocacao, dados.contrato_id)
    if contrato is None:
        raise RegraNegocio("Contrato não encontrado.")
    arquivo_id = dados.referencia.removeprefix("arquivo:")
    if db.get(Arquivo, arquivo_id) is None:
        raise RegraNegocio("Envie o arquivo antes de publicá-lo.")
    if not dados.titulo.strip():
        raise RegraNegocio("Informe o título do documento.")
    a = db.get(m.ArquivoContrato, id)
    novo = a is None
    if novo:
        a = m.ArquivoContrato(id=id, origem=OrigemArquivo.imobiliaria)
        db.add(a)
        response.status_code = 201
    publicado_agora = dados.visivel_inquilino and (novo or not a.visivel_inquilino)
    a.contrato_id = contrato.id
    a.tipo = dados.tipo
    a.titulo = dados.titulo.strip()
    a.observacao = dados.observacao.strip()
    a.arquivo_id = arquivo_id
    a.visivel_inquilino = dados.visivel_inquilino
    if publicado_agora and a.origem == OrigemArquivo.imobiliaria:
        services.avisar(
            db, contrato.id, "Novo documento disponível",
            f'"{a.titulo}" ({a.tipo.rotulo}) está disponível em Documentos.',
        )  # fmt: skip
    db.commit()
    return _arquivo_saida(a)


@router.delete("/arquivos/{id}", status_code=204)
def remover_arquivo(id: str, db: Db):
    a = db.get(m.ArquivoContrato, validar_id(id))
    if a is None:
        raise NaoEncontrado("Arquivo não encontrado.")
    db.delete(a)
    db.commit()
    return Response(status_code=204)


# ------------------------------------------------------------ Comunicados


@router.get("/comunicados", response_model=list[ComunicadoSaida])
def listar_comunicados(db: Db, contrato_id: str | None = Query(None, alias="contratoId")):
    q = sa.select(m.Comunicado).order_by(m.Comunicado.criado_em.desc()).limit(500)
    if contrato_id:
        q = q.where(sa.or_(m.Comunicado.contrato_id == contrato_id, m.Comunicado.contrato_id.is_(None)))
    avisos = db.scalars(q).all()
    leituras = dict(db.execute(
        sa.select(m.LeituraComunicado.comunicado_id, sa.func.count())
        .where(m.LeituraComunicado.comunicado_id.in_([c.id for c in avisos]))
        .group_by(m.LeituraComunicado.comunicado_id)
    ).all()) if avisos else {}  # fmt: skip
    return [
        ComunicadoSaida(
            id=c.id, contrato_id=c.contrato_id, titulo=c.titulo, mensagem=c.mensagem,
            automatico=c.automatico, criado_em=c.criado_em, leituras=leituras.get(c.id, 0),
        )  # fmt: skip
        for c in avisos
    ]


@router.post("/comunicados", response_model=ComunicadoSaida, status_code=201)
def enviar_comunicado(dados: ComunicadoEntrada, db: Db, usuario: UsuarioLogado):
    if not dados.titulo.strip() or not dados.mensagem.strip():
        raise RegraNegocio("Informe o título e a mensagem.")
    if dados.contrato_id and db.get(ContratoLocacao, dados.contrato_id) is None:
        raise RegraNegocio("Contrato não encontrado.")
    c = services.avisar(
        db, dados.contrato_id, dados.titulo.strip(), dados.mensagem.strip(),
        automatico=False, enviado_por_id=usuario.id,
    )  # fmt: skip
    db.commit()
    return ComunicadoSaida(
        id=c.id, contrato_id=c.contrato_id, titulo=c.titulo, mensagem=c.mensagem,
        automatico=False, criado_em=c.criado_em, leituras=0,
    )  # fmt: skip


@router.delete("/comunicados/{id}", status_code=204)
def remover_comunicado(id: str, db: Db):
    c = db.get(m.Comunicado, validar_id(id))
    if c is None:
        raise NaoEncontrado("Comunicado não encontrado.")
    db.delete(c)
    db.commit()
    return Response(status_code=204)

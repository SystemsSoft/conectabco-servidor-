"""Consultas do CRM no banco."""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.modules.crm import models as m
from app.modules.crm.enums import (
    EtapaFunil,
    Finalidade,
    OrigemContato,
    PapelContato,
    StatusImovel,
    TipoEvento,
    TipoImovel,
)


def _contem(*colunas: sa.ColumnElement, termo: str) -> sa.ColumnElement[bool]:
    padrao = f"%{termo.strip()}%"
    return sa.or_(*(c.ilike(padrao) for c in colunas))


def _paginar(
    db: Session, consulta: sa.Select, limite: int, deslocamento: int
) -> tuple[Sequence, int]:
    total = db.scalar(sa.select(sa.func.count()).select_from(consulta.subquery()))
    itens = db.scalars(consulta.limit(limite).offset(deslocamento)).all()
    return itens, total or 0


class ImovelRepository:
    def __init__(self, db: Session):
        self.db = db

    def obter(self, id: str) -> m.Imovel | None:
        return self.db.get(m.Imovel, id)

    def listar(
        self,
        *,
        busca: str | None = None,
        finalidade: Finalidade | None = None,
        status: StatusImovel | None = None,
        tipo: TipoImovel | None = None,
        cidade: str | None = None,
        proprietario_id: str | None = None,
        limite: int = 100,
        deslocamento: int = 0,
    ) -> tuple[Sequence[m.Imovel], int]:
        q = sa.select(m.Imovel)
        if busca:
            I = m.Imovel  # noqa: E741
            q = q.where(
                _contem(
                    I.codigo, I.titulo, I.bairro, I.cidade, I.logradouro,
                    I.condominio_nome, termo=busca,
                )  # fmt: skip
            )
        if finalidade:
            q = q.where(
                m.Imovel.finalidades.any(m.ImovelFinalidade.finalidade == finalidade)
            )
        if status:
            q = q.where(m.Imovel.status == status)
        if tipo:
            q = q.where(m.Imovel.tipo == tipo)
        if cidade:
            q = q.where(m.Imovel.cidade.ilike(cidade.strip()))
        if proprietario_id:
            q = q.where(m.Imovel.proprietario_id == proprietario_id)
        q = q.order_by(m.Imovel.criado_em.desc(), m.Imovel.codigo.desc())
        return _paginar(self.db, q, limite, deslocamento)

    def disponiveis(self) -> Sequence[m.Imovel]:
        return self.db.scalars(
            sa.select(m.Imovel).where(m.Imovel.status == StatusImovel.disponivel)
        ).all()

    def adicionar(self, imovel: m.Imovel) -> None:
        self.db.add(imovel)

    def remover(self, imovel: m.Imovel) -> None:
        self.db.delete(imovel)


class ContatoRepository:
    def __init__(self, db: Session):
        self.db = db

    def obter(self, id: str) -> m.Contato | None:
        return self.db.get(m.Contato, id)

    def existe(self, id: str) -> bool:
        return self.db.scalar(sa.select(m.Contato.id).where(m.Contato.id == id)) is not None

    def listar(
        self,
        *,
        busca: str | None = None,
        papel: PapelContato | None = None,
        etapa: EtapaFunil | None = None,
        origem: OrigemContato | None = None,
        com_perfil: bool | None = None,
        limite: int = 100,
        deslocamento: int = 0,
    ) -> tuple[Sequence[m.Contato], int]:
        q = sa.select(m.Contato)
        if busca:
            C = m.Contato
            q = q.where(
                _contem(
                    C.nome, C.email, C.documento, C.telefone, C.celular,
                    termo=busca,
                )  # fmt: skip
            )
        if papel:
            q = q.where(m.Contato.papeis.any(m.ContatoPapel.papel == papel))
        if etapa:
            q = q.where(m.Contato.etapa == etapa)
        if origem:
            q = q.where(m.Contato.origem == origem)
        if com_perfil is not None:
            tem = m.Contato.perfil.has()
            q = q.where(tem if com_perfil else ~tem)
        q = q.order_by(m.Contato.nome)
        return _paginar(self.db, q, limite, deslocamento)

    def com_perfil(self) -> Sequence[m.Contato]:
        return self.db.scalars(
            sa.select(m.Contato).where(m.Contato.perfil.has())
        ).all()

    def adicionar(self, contato: m.Contato) -> None:
        self.db.add(contato)

    def remover(self, contato: m.Contato) -> None:
        self.db.delete(contato)


class EventoRepository:
    def __init__(self, db: Session):
        self.db = db

    def obter(self, id: str) -> m.Evento | None:
        return self.db.get(m.Evento, id)

    def listar(
        self,
        *,
        contato_id: str | None = None,
        imovel_id: str | None = None,
        tipo: TipoEvento | None = None,
        concluido: bool | None = None,
        de: datetime | None = None,
        ate: datetime | None = None,
        limite: int = 100,
        deslocamento: int = 0,
    ) -> tuple[Sequence[m.Evento], int]:
        q = sa.select(m.Evento)
        if contato_id:
            q = q.where(m.Evento.contato_id == contato_id)
        if imovel_id:
            q = q.where(m.Evento.imovel_id == imovel_id)
        if tipo:
            q = q.where(m.Evento.tipo == tipo)
        if concluido is not None:
            q = q.where(m.Evento.concluido == concluido)
        if de:
            q = q.where(m.Evento.data_hora >= de)
        if ate:
            q = q.where(m.Evento.data_hora < ate)
        # Itens com data primeiro, em ordem cronológica; anotações no fim.
        q = q.order_by(
            m.Evento.data_hora.is_(None), m.Evento.data_hora, m.Evento.criado_em
        )
        return _paginar(self.db, q, limite, deslocamento)

    def pendentes_ate(self, limite: datetime) -> Sequence[m.Evento]:
        return self.db.scalars(
            sa.select(m.Evento)
            .where(
                m.Evento.concluido.is_(False),
                m.Evento.data_hora.is_not(None),
                m.Evento.data_hora < limite,
            )
            .order_by(m.Evento.data_hora)
        ).all()

    def desvincular_contato(self, contato_id: str) -> None:
        self.db.execute(
            sa.update(m.Evento)
            .where(m.Evento.contato_id == contato_id)
            .values(contato_id=None)
        )

    def desvincular_imovel(self, imovel_id: str) -> None:
        self.db.execute(
            sa.update(m.Evento)
            .where(m.Evento.imovel_id == imovel_id)
            .values(imovel_id=None)
        )

    def adicionar(self, evento: m.Evento) -> None:
        self.db.add(evento)

    def remover(self, evento: m.Evento) -> None:
        self.db.delete(evento)

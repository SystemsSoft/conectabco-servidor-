"""Regras de negócio do CRM (equivalentes aos casos de uso do front-end)."""

from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.errors import NaoEncontrado, RegraNegocio, validar_id
from app.core.schemas import Pagina
from app.core.sequencias import proximo_valor
from app.core.tempo import agora
from app.modules.crm import mapeamento as mp
from app.modules.crm import models as m
from app.modules.crm import schemas as s
from app.modules.crm.cruzamento import SugerirNegocios
from app.modules.crm.enums import TipoEvento
from app.modules.crm.repositories import (
    ContatoRepository,
    EventoRepository,
    ImovelRepository,
)


def _pagina[T](itens: list[T], total: int, limite: int, deslocamento: int) -> Pagina[T]:
    return Pagina[T](
        itens=itens, total=total, limite=limite, deslocamento=deslocamento
    )


# ----------------------------------------------------------------- Imóveis


class ImovelService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ImovelRepository(db)
        self.contatos = ContatoRepository(db)
        self.eventos = EventoRepository(db)

    def listar(self, limite: int, deslocamento: int, **filtros) -> Pagina[s.ImovelSaida]:
        itens, total = self.repo.listar(
            limite=limite, deslocamento=deslocamento, **filtros
        )
        return _pagina([mp.imovel_saida(i) for i in itens], total, limite, deslocamento)

    def obter(self, id: str) -> s.ImovelSaida:
        return mp.imovel_saida(self._buscar(id))

    def criar(self, dados: s.ImovelEntrada) -> s.ImovelSaida:
        self._validar(dados)
        imovel = m.Imovel(codigo=self._proximo_codigo())
        mp.aplicar_imovel(imovel, dados)
        self.repo.adicionar(imovel)
        self.db.commit()
        return mp.imovel_saida(imovel)

    def salvar(self, id: str, dados: s.ImovelEntrada) -> tuple[s.ImovelSaida, bool]:
        """Atualiza o imóvel ou o cria com o id informado pelo app.
        Devolve (imóvel, criado)."""
        imovel = self.repo.obter(validar_id(id))
        self._validar(dados)
        criado = imovel is None
        if criado:
            imovel = m.Imovel(id=validar_id(id), codigo=self._proximo_codigo())
            self.repo.adicionar(imovel)
        mp.aplicar_imovel(imovel, dados)
        self.db.commit()
        return mp.imovel_saida(imovel), criado

    def remover(self, id: str) -> None:
        """Remove o imóvel e desvincula os itens da agenda que apontavam para ele."""
        imovel = self._buscar(id)
        self.eventos.desvincular_imovel(id)
        self.repo.remover(imovel)
        self.db.commit()

    def _buscar(self, id: str) -> m.Imovel:
        imovel = self.repo.obter(id)
        if imovel is None:
            raise NaoEncontrado("Imóvel não encontrado.")
        return imovel

    def _validar(self, dados: s.ImovelEntrada) -> None:
        if not dados.titulo.strip():
            raise RegraNegocio("Informe o título do imóvel.")
        if not dados.finalidades:
            raise RegraNegocio("Selecione ao menos uma finalidade.")
        if dados.proprietario_id and not self.contatos.existe(dados.proprietario_id):
            raise RegraNegocio("Proprietário não encontrado.")

    def _proximo_codigo(self) -> str:
        return f"IM-{proximo_valor(self.db, 'imovel_codigo'):04d}"


# ---------------------------------------------------------------- Contatos


class ContatoService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ContatoRepository(db)
        self.eventos = EventoRepository(db)

    def listar(self, limite: int, deslocamento: int, **filtros) -> Pagina[s.ContatoSaida]:
        itens, total = self.repo.listar(
            limite=limite, deslocamento=deslocamento, **filtros
        )
        return _pagina(
            [mp.contato_saida(c) for c in itens], total, limite, deslocamento
        )

    def obter(self, id: str) -> s.ContatoSaida:
        return mp.contato_saida(self._buscar(id))

    def criar(self, dados: s.ContatoEntrada) -> s.ContatoSaida:
        self._validar(dados)
        contato = m.Contato()
        mp.aplicar_contato(contato, dados)
        self.repo.adicionar(contato)
        self.db.commit()
        return mp.contato_saida(contato)

    def salvar(self, id: str, dados: s.ContatoEntrada) -> tuple[s.ContatoSaida, bool]:
        """Atualiza o contato ou o cria com o id informado pelo app."""
        contato = self.repo.obter(validar_id(id))
        self._validar(dados)
        criado = contato is None
        if criado:
            contato = m.Contato(id=validar_id(id))
            self.repo.adicionar(contato)
        mp.aplicar_contato(contato, dados)
        self.db.commit()
        return mp.contato_saida(contato), criado

    def remover(self, id: str) -> None:
        """Remove o contato, desvincula a agenda e os imóveis de que era dono."""
        contato = self._buscar(id)
        self.eventos.desvincular_contato(id)
        self.db.execute(
            sa.update(m.Imovel)
            .where(m.Imovel.proprietario_id == id)
            .values(proprietario_id=None)
        )
        self.repo.remover(contato)
        self.db.commit()

    def _buscar(self, id: str) -> m.Contato:
        contato = self.repo.obter(id)
        if contato is None:
            raise NaoEncontrado("Contato não encontrado.")
        return contato

    @staticmethod
    def _validar(dados: s.ContatoEntrada) -> None:
        if not dados.nome.strip():
            raise RegraNegocio("Informe o nome do contato.")
        p = dados.perfil
        if (
            p is not None
            and p.valor_min is not None
            and p.valor_max is not None
            and p.valor_min > p.valor_max
        ):
            raise RegraNegocio("O valor mínimo é maior que o máximo.")


# ------------------------------------------------- Central de Relacionamento


class EventoService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = EventoRepository(db)
        self.contatos = ContatoRepository(db)
        self.imoveis = ImovelRepository(db)

    def listar(self, limite: int, deslocamento: int, **filtros) -> Pagina[s.EventoSaida]:
        itens, total = self.repo.listar(
            limite=limite, deslocamento=deslocamento, **filtros
        )
        return _pagina([mp.evento_saida(e) for e in itens], total, limite, deslocamento)

    def pendentes(self, referencia: datetime | None = None) -> list[s.EventoSaida]:
        """Compromissos atrasados ou de hoje ainda não concluídos (o sino)."""
        h = referencia or agora()
        fim_hoje = datetime(h.year, h.month, h.day) + timedelta(days=1)
        return [mp.evento_saida(e) for e in self.repo.pendentes_ate(fim_hoje)]

    def obter(self, id: str) -> s.EventoSaida:
        return mp.evento_saida(self._buscar(id))

    def criar(self, dados: s.EventoEntrada) -> s.EventoSaida:
        self._validar(dados)
        evento = m.Evento()
        mp.aplicar_evento(evento, dados)
        self.repo.adicionar(evento)
        self.db.commit()
        return mp.evento_saida(evento)

    def salvar(self, id: str, dados: s.EventoEntrada) -> tuple[s.EventoSaida, bool]:
        """Atualiza o item da agenda ou o cria com o id informado pelo app."""
        evento = self.repo.obter(validar_id(id))
        self._validar(dados)
        criado = evento is None
        if criado:
            evento = m.Evento(id=validar_id(id))
            self.repo.adicionar(evento)
        mp.aplicar_evento(evento, dados)
        self.db.commit()
        return mp.evento_saida(evento), criado

    def alternar_conclusao(self, id: str) -> s.EventoSaida:
        evento = self._buscar(id)
        evento.concluido = not evento.concluido
        self.db.commit()
        return mp.evento_saida(evento)

    def remover(self, id: str) -> None:
        self.repo.remover(self._buscar(id))
        self.db.commit()

    def _buscar(self, id: str) -> m.Evento:
        evento = self.repo.obter(id)
        if evento is None:
            raise NaoEncontrado("Item da agenda não encontrado.")
        return evento

    def _validar(self, dados: s.EventoEntrada) -> None:
        if not dados.titulo.strip():
            raise RegraNegocio("Informe o título.")
        if dados.tipo != TipoEvento.anotacao and dados.data_hora is None:
            raise RegraNegocio("Informe a data e hora.")
        if dados.contato_id and not self.contatos.existe(dados.contato_id):
            raise RegraNegocio("Contato não encontrado.")
        if dados.imovel_id and self.imoveis.obter(dados.imovel_id) is None:
            raise RegraNegocio("Imóvel não encontrado.")


# --------------------------------------------------------- Cruzamento


class CruzamentoService:
    def __init__(self, db: Session):
        self.imoveis = ImovelRepository(db)
        self.contatos = ContatoRepository(db)
        self.sugerir = SugerirNegocios()

    def para_contato(self, contato_id: str) -> list[s.Sugestao]:
        contato = self.contatos.obter(contato_id)
        if contato is None:
            raise NaoEncontrado("Contato não encontrado.")
        imoveis = [mp.imovel_saida(i) for i in self.imoveis.disponiveis()]
        return self.sugerir.para_contato(mp.contato_saida(contato), imoveis)

    def para_imovel(self, imovel_id: str) -> list[s.Sugestao]:
        imovel = self.imoveis.obter(imovel_id)
        if imovel is None:
            raise NaoEncontrado("Imóvel não encontrado.")
        contatos = [mp.contato_saida(c) for c in self.contatos.com_perfil()]
        return self.sugerir.para_imovel(mp.imovel_saida(imovel), contatos)

    def resumo(self) -> s.ResumoCruzamento:
        imoveis = [mp.imovel_saida(i) for i in self.imoveis.disponiveis()]
        contatos = [mp.contato_saida(c) for c in self.contatos.com_perfil()]
        return s.ResumoCruzamento(
            total_sugestoes=self.sugerir.total(contatos, imoveis),
            contatos_com_perfil=len(contatos),
            imoveis_disponiveis=len(imoveis),
        )

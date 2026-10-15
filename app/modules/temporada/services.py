"""Regras das reservas (equivalentes aos casos de uso do app), incluindo a
checagem de datas sobrepostas no servidor — protege contra duas pessoas
reservarem o mesmo período ao mesmo tempo."""

from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.errors import NaoEncontrado, RegraNegocio, validar_id
from app.core.schemas import Pagina, pagina
from app.core.sequencias import proximo_valor
from app.modules.crm.repositories import ContatoRepository, ImovelRepository
from app.modules.temporada import models as m
from app.modules.temporada import schemas as s
from app.modules.temporada.enums import SituacaoReserva


def _arredondar(v: float) -> float:
    return round(v + 1e-9, 2)


def _totais(r) -> dict:
    noites = (r.check_out - r.check_in).days
    subtotal = _arredondar(r.valor_diaria * noites)
    total = 0.0 if r.bloqueio else _arredondar(subtotal + r.taxa_limpeza - r.desconto)
    return {"noites": noites, "subtotal": subtotal, "total": total,
            "saldo": _arredondar(total - r.valor_pago)}  # fmt: skip


def reserva_saida(r: m.Reserva) -> s.ReservaSaida:
    t = _totais(r)
    return s.ReservaSaida.model_validate(
        {
            **{c.key: getattr(r, c.key) for c in m.Reserva.__mapper__.columns},
            "noites": t["noites"],
            "total": t["total"],
            "saldo": t["saldo"],
        }
    )


def _data(d: date) -> str:
    return d.strftime("%d/%m/%Y")


class ReservaService:
    def __init__(self, db: Session):
        self.db = db
        self.imoveis = ImovelRepository(db)
        self.contatos = ContatoRepository(db)

    def listar(
        self, limite: int, deslocamento: int, *, imovel_id=None, situacao=None,
        de: date | None = None, ate: date | None = None,
    ) -> Pagina[s.ReservaSaida]:  # fmt: skip
        q = sa.select(m.Reserva)
        if imovel_id:
            q = q.where(m.Reserva.imovel_id == imovel_id)
        if situacao:
            q = q.where(m.Reserva.situacao == situacao)
        if de:  # reservas que ainda ocupam alguma noite a partir de "de"
            q = q.where(m.Reserva.check_out > de)
        if ate:
            q = q.where(m.Reserva.check_in < ate)
        total = self.db.scalar(sa.select(sa.func.count()).select_from(q.subquery())) or 0
        itens = self.db.scalars(
            q.order_by(m.Reserva.check_in, m.Reserva.numero).limit(limite).offset(deslocamento)
        ).all()
        return pagina([reserva_saida(r) for r in itens], total, limite, deslocamento)

    def obter(self, id: str) -> s.ReservaSaida:
        return reserva_saida(self._buscar(id))

    def conflitos(
        self, imovel_id: str, check_in: date, check_out: date, ignorar_id: str | None = None
    ) -> list[s.ReservaSaida]:
        """Reservas/bloqueios ativos que ocupam alguma noite do período."""
        q = sa.select(m.Reserva).where(
            m.Reserva.imovel_id == imovel_id,
            m.Reserva.situacao != SituacaoReserva.cancelada,
            m.Reserva.check_in < check_out,
            m.Reserva.check_out > check_in,
        )
        if ignorar_id:
            q = q.where(m.Reserva.id != ignorar_id)
        return [reserva_saida(r) for r in self.db.scalars(q.order_by(m.Reserva.check_in))]

    def salvar(self, id: str, dados: s.ReservaEntrada) -> tuple[s.ReservaSaida, bool]:
        """Atualiza a reserva ou a cria (número RES-0001...) se o id é novo."""
        id = validar_id(id)
        self._validar(id, dados)
        reserva = self.db.get(m.Reserva, id)
        criado = reserva is None
        if criado:
            numero = proximo_valor(self.db, "reserva_numero")
            reserva = m.Reserva(id=id, numero=f"RES-{numero:04d}")
            self.db.add(reserva)
        for campo, valor in dados.model_dump().items():
            setattr(reserva, campo, valor)
        if reserva.bloqueio:
            reserva.hospede_id = None
        self.db.commit()
        return reserva_saida(reserva), criado

    def remover(self, id: str) -> None:
        self.db.delete(self._buscar(id))
        self.db.commit()

    def _buscar(self, id: str) -> m.Reserva:
        reserva = self.db.get(m.Reserva, id)
        if reserva is None:
            raise NaoEncontrado("Reserva não encontrada.")
        return reserva

    def _validar(self, id: str, r: s.ReservaEntrada) -> None:
        if not r.imovel_id:
            raise RegraNegocio("Selecione o imóvel.")
        if self.imoveis.obter(r.imovel_id) is None:
            raise RegraNegocio("Imóvel não encontrado.")
        if not r.bloqueio:
            if not r.hospede_id:
                raise RegraNegocio("Selecione o hóspede.")
            if not self.contatos.existe(r.hospede_id):
                raise RegraNegocio("Hóspede não encontrado.")
        if r.check_out <= r.check_in:
            raise RegraNegocio("O check-out deve ser depois do check-in.")
        if not r.bloqueio:
            t = _totais(r)
            if r.hospedes < 1:
                raise RegraNegocio("Informe o número de hóspedes.")
            if r.valor_diaria <= 0:
                raise RegraNegocio("Informe o valor da diária.")
            if r.desconto > t["subtotal"] + r.taxa_limpeza:
                raise RegraNegocio("O desconto é maior que o valor da estadia.")
            if r.valor_pago > t["total"] + 0.001:
                raise RegraNegocio("O valor pago é maior que o total da reserva.")
        if r.situacao != SituacaoReserva.cancelada:
            conflitos = self.conflitos(r.imovel_id, r.check_in, r.check_out, ignorar_id=id)
            if conflitos:
                c = conflitos[0]
                quem = "um bloqueio" if c.bloqueio else f"a reserva {c.numero}"
                raise RegraNegocio(
                    f"Período indisponível: conflita com {quem} "
                    f"({_data(c.check_in)} a {_data(c.check_out)})."
                )

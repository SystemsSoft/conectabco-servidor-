"""Regras de negócio da locação (equivalentes aos casos de uso do app).

Os cálculos (geração das cobranças do mês, encargos, repasse e IR) ficam no
app por enquanto; o servidor valida e guarda o resultado."""

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.errors import NaoEncontrado, RegraNegocio, validar_id
from app.core.schemas import Pagina, pagina
from app.core.sequencias import proximo_valor
from app.modules.crm.repositories import ContatoRepository, ImovelRepository
from app.modules.locacao import mapeamento as mp
from app.modules.locacao import models as m
from app.modules.locacao import schemas as s
from app.modules.locacao.enums import NaturezaDespesa
from app.modules.locacao.repositories import (
    CobrancaRepository,
    ContratoRepository,
    DespesaRepository,
    RepasseRepository,
)


def _contrato_existe(db: Session, contrato_id: str) -> None:
    if db.get(m.ContratoLocacao, contrato_id) is None:
        raise RegraNegocio("Contrato não encontrado.")


# --------------------------------------------------------------- Contratos


class ContratoService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ContratoRepository(db)
        self.imoveis = ImovelRepository(db)
        self.contatos = ContatoRepository(db)

    def listar(self, limite: int, deslocamento: int, **filtros) -> Pagina[s.ContratoSaida]:
        itens, total = self.repo.listar(limite=limite, deslocamento=deslocamento, **filtros)
        return pagina([mp.contrato_saida(c) for c in itens], total, limite, deslocamento)

    def obter(self, id: str) -> s.ContratoSaida:
        return mp.contrato_saida(self._buscar(id))

    def salvar(self, id: str, dados: s.ContratoEntrada) -> tuple[s.ContratoSaida, bool]:
        """Atualiza o contrato ou o cria (com número LOC-0001...) se o id é novo."""
        id = validar_id(id)
        self._validar(dados)
        contrato = self.repo.obter(id)
        criado = contrato is None
        if criado:
            numero = proximo_valor(self.db, "contrato_locacao_numero")
            contrato = m.ContratoLocacao(id=id, numero=f"LOC-{numero:04d}")
            self.db.add(contrato)
        mp.aplicar_contrato(contrato, dados)
        self.db.commit()
        return mp.contrato_saida(contrato), criado

    def remover(self, id: str) -> None:
        """Remove o contrato com despesas, cobranças e repasses."""
        contrato = self._buscar(id)
        cobrancas = sa.select(m.Cobranca.id).where(m.Cobranca.contrato_id == id)
        self.db.execute(
            sa.delete(m.RepasseRealizado).where(
                m.RepasseRealizado.cobranca_id.in_(cobrancas)
            )
        )
        self.db.execute(
            sa.delete(m.ItemCobranca).where(m.ItemCobranca.cobranca_id.in_(cobrancas))
        )
        self.db.execute(sa.delete(m.Cobranca).where(m.Cobranca.contrato_id == id))
        self.db.execute(sa.delete(m.Despesa).where(m.Despesa.contrato_id == id))
        self.db.delete(contrato)
        self.db.commit()

    def _buscar(self, id: str) -> m.ContratoLocacao:
        contrato = self.repo.obter(id)
        if contrato is None:
            raise NaoEncontrado("Contrato não encontrado.")
        return contrato

    def _validar(self, c: s.ContratoEntrada) -> None:
        if not c.imovel_id:
            raise RegraNegocio("Selecione o imóvel.")
        if self.imoveis.obter(c.imovel_id) is None:
            raise RegraNegocio("Imóvel não encontrado.")
        if not c.locatario_id:
            raise RegraNegocio("Selecione o locatário.")
        if not self.contatos.existe(c.locatario_id):
            raise RegraNegocio("Locatário não encontrado.")
        if c.fiador_id and not self.contatos.existe(c.fiador_id):
            raise RegraNegocio("Fiador não encontrado.")
        if c.valor_aluguel <= 0:
            raise RegraNegocio("Informe o valor do aluguel.")
        if c.prazo_meses <= 0:
            raise RegraNegocio("Informe o prazo.")
        if not 1 <= c.dia_vencimento <= 31:
            raise RegraNegocio("Dia de vencimento deve ser de 1 a 31.")
        if not c.beneficiarios:
            raise RegraNegocio("Informe ao menos um beneficiário.")
        soma = sum(b.percentual for b in c.beneficiarios)
        if abs(soma - 100) > 0.01:
            raise RegraNegocio(
                f"Os percentuais dos beneficiários somam {soma:.2f}%; devem somar 100%."
            )
        if any(b.contato_id == c.locatario_id for b in c.beneficiarios):
            raise RegraNegocio("O locatário não pode ser beneficiário do próprio contrato.")
        for b in c.beneficiarios:
            if not self.contatos.existe(b.contato_id):
                raise RegraNegocio("Beneficiário não encontrado.")


# ---------------------------------------------------------------- Despesas


class DespesaService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = DespesaRepository(db)

    def listar(self, limite: int, deslocamento: int, **filtros) -> Pagina[s.DespesaSaida]:
        itens, total = self.repo.listar(limite=limite, deslocamento=deslocamento, **filtros)
        return pagina([mp.despesa_saida(d) for d in itens], total, limite, deslocamento)

    def salvar(self, id: str, dados: s.DespesaEntrada) -> tuple[s.DespesaSaida, bool]:
        id = validar_id(id)
        self._validar(dados)
        despesa = self.repo.obter(id)
        criado = despesa is None
        if criado:
            despesa = m.Despesa(id=id)
            self.db.add(despesa)
        mp.aplicar_despesa(despesa, dados)
        self.db.commit()
        return mp.despesa_saida(despesa), criado

    def remover(self, id: str) -> None:
        despesa = self.repo.obter(id)
        if despesa is None:
            raise NaoEncontrado("Despesa não encontrada.")
        self.db.delete(despesa)
        self.db.commit()

    def _validar(self, d: s.DespesaEntrada) -> None:
        if not d.contrato_id:
            raise RegraNegocio("Selecione o contrato.")
        _contrato_existe(self.db, d.contrato_id)
        if not d.descricao.strip():
            raise RegraNegocio("Informe a descrição.")
        if d.valor <= 0:
            raise RegraNegocio("Informe o valor.")
        if (
            d.natureza == NaturezaDespesa.fixa
            and d.competencia_fim is not None
            and d.competencia_fim.replace(day=1) < d.competencia_inicio.replace(day=1)
        ):
            raise RegraNegocio("O fim deve ser posterior ao início.")


# --------------------------------------------------------------- Cobranças


class CobrancaService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = CobrancaRepository(db)

    def listar(self, limite: int, deslocamento: int, **filtros) -> Pagina[s.CobrancaSaida]:
        itens, total = self.repo.listar(limite=limite, deslocamento=deslocamento, **filtros)
        return pagina([mp.cobranca_saida(c) for c in itens], total, limite, deslocamento)

    def obter(self, id: str) -> s.CobrancaSaida:
        cobranca = self.repo.obter(id)
        if cobranca is None:
            raise NaoEncontrado("Cobrança não encontrada.")
        return mp.cobranca_saida(cobranca)

    def salvar(self, id: str, dados: s.CobrancaEntrada) -> tuple[s.CobrancaSaida, bool]:
        id = validar_id(id)
        _contrato_existe(self.db, dados.contrato_id)
        if not dados.itens:
            raise RegraNegocio("A cobrança precisa de ao menos um item.")
        dados.competencia = dados.competencia.replace(day=1)
        outra = self.repo.da_competencia(dados.contrato_id, dados.competencia)
        if outra is not None and outra.id != id:
            raise RegraNegocio("Já existe cobrança deste contrato na competência.")
        cobranca = self.repo.obter(id)
        criado = cobranca is None
        if criado:
            cobranca = m.Cobranca(id=id)
            self.db.add(cobranca)
        mp.aplicar_cobranca(cobranca, dados)
        self.db.commit()
        return mp.cobranca_saida(cobranca), criado

    def remover(self, id: str) -> None:
        cobranca = self.repo.obter(id)
        if cobranca is None:
            raise NaoEncontrado("Cobrança não encontrada.")
        self.db.execute(
            sa.delete(m.RepasseRealizado).where(m.RepasseRealizado.cobranca_id == id)
        )
        self.db.delete(cobranca)
        self.db.commit()


# ---------------------------------------------------------------- Repasses


class RepasseService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = RepasseRepository(db)
        self.cobrancas = CobrancaRepository(db)
        self.contatos = ContatoRepository(db)

    def listar(self, cobranca_id: str | None = None) -> list[s.RepasseSaida]:
        return [s.RepasseSaida.model_validate(r) for r in self.repo.listar(cobranca_id)]

    def marcar(self, cobranca_id: str, contato_id: str, dados: s.RepasseEntrada) -> s.RepasseSaida:
        if self.cobrancas.obter(cobranca_id) is None:
            raise RegraNegocio("Cobrança não encontrada.")
        if not self.contatos.existe(contato_id):
            raise RegraNegocio("Beneficiário não encontrado.")
        repasse = self.repo.obter(cobranca_id, contato_id)
        if repasse is None:
            repasse = m.RepasseRealizado(cobranca_id=cobranca_id, contato_id=contato_id)
            self.db.add(repasse)
        repasse.data = dados.data
        self.db.commit()
        return s.RepasseSaida.model_validate(repasse)

    def desmarcar(self, cobranca_id: str, contato_id: str) -> None:
        repasse = self.repo.obter(cobranca_id, contato_id)
        if repasse is not None:
            self.db.delete(repasse)
            self.db.commit()

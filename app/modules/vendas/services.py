"""Regras de negócio das vendas (equivalentes aos casos de uso do app).

A tabela de parcelas (Price/SAC) e os encargos são calculados no app; o
servidor valida e guarda."""

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.errors import NaoEncontrado, RegraNegocio, validar_id
from app.core.schemas import Pagina, pagina
from app.core.sequencias import proximo_valor
from app.modules.crm.repositories import ContatoRepository, ImovelRepository
from app.modules.vendas import models as m
from app.modules.vendas import schemas as s
from app.modules.vendas.enums import FormaPagamento, PapelParticipacao, StatusParcela

# ---------------------------------------------------------------- Mapeamento


def _colunas(obj, modelo) -> dict:
    return {c.key: getattr(obj, c.key) for c in modelo.__mapper__.columns}


def _participacoes(v: m.Venda, papel: PapelParticipacao) -> list[dict]:
    return [
        {"contato_id": p.contato_id, "percentual": p.percentual, "paga_em": p.paga_em}
        for p in v.participacoes
        if p.papel == papel
    ]


def venda_saida(v: m.Venda) -> s.VendaSaida:
    plano = None
    if v.plano_numero_parcelas is not None:
        plano = {
            "numero_parcelas": v.plano_numero_parcelas,
            "taxa_juros_mes": v.plano_taxa_juros_mes,
            "sistema": v.plano_sistema,
            "primeiro_vencimento": v.plano_primeiro_vencimento,
        }
    return s.VendaSaida.model_validate(
        {
            **_colunas(v, m.Venda),
            "compradores": [c.contato_id for c in v.compradores],
            "vendedores": _participacoes(v, PapelParticipacao.vendedor),
            "corretores": _participacoes(v, PapelParticipacao.corretor),
            "plano": plano,
        }
    )


def _aplicar_venda(v: m.Venda, e: s.VendaEntrada) -> None:
    excluir = {"compradores", "vendedores", "corretores", "plano"}
    for campo, valor in e.model_dump(exclude=excluir).items():
        setattr(v, campo, valor)
    p = e.plano
    v.plano_numero_parcelas = p.numero_parcelas if p else None
    v.plano_taxa_juros_mes = p.taxa_juros_mes if p else None
    v.plano_sistema = p.sistema if p else None
    v.plano_primeiro_vencimento = p.primeiro_vencimento if p else None
    v.compradores = [
        m.VendaComprador(contato_id=c, ordem=i)
        for i, c in enumerate(dict.fromkeys(e.compradores))
    ]
    v.participacoes = [
        m.Participacao(
            papel=papel, ordem=i, contato_id=p.contato_id,
            percentual=p.percentual, paga_em=p.paga_em,
        )  # fmt: skip
        for papel, lista in (
            (PapelParticipacao.vendedor, e.vendedores),
            (PapelParticipacao.corretor, e.corretores),
        )
        for i, p in enumerate(lista)
    ]


def parcela_saida(p: m.Parcela) -> s.ParcelaSaida:
    return s.ParcelaSaida.model_validate(p)


# -------------------------------------------------------------------- Vendas


class VendaService:
    def __init__(self, db: Session):
        self.db = db
        self.imoveis = ImovelRepository(db)
        self.contatos = ContatoRepository(db)

    def listar(
        self, limite: int, deslocamento: int, *, status=None, imovel_id=None, busca=None
    ) -> Pagina[s.VendaSaida]:
        q = sa.select(m.Venda)
        if status:
            q = q.where(m.Venda.status == status)
        if imovel_id:
            q = q.where(m.Venda.imovel_id == imovel_id)
        if busca:
            q = q.where(m.Venda.numero.ilike(f"%{busca.strip()}%"))
        total = self.db.scalar(sa.select(sa.func.count()).select_from(q.subquery())) or 0
        itens = self.db.scalars(
            q.order_by(m.Venda.numero).limit(limite).offset(deslocamento)
        ).all()
        return pagina([venda_saida(v) for v in itens], total, limite, deslocamento)

    def obter(self, id: str) -> s.VendaSaida:
        return venda_saida(self._buscar(id))

    def salvar(self, id: str, dados: s.VendaEntrada) -> tuple[s.VendaSaida, bool]:
        """Atualiza a venda ou a cria (número VEN-0001...) se o id é novo."""
        id = validar_id(id)
        self._validar(dados)
        venda = self.db.get(m.Venda, id)
        criado = venda is None
        if criado:
            numero = proximo_valor(self.db, "venda_numero")
            venda = m.Venda(id=id, numero=f"VEN-{numero:04d}")
            self.db.add(venda)
        elif self._condicoes_mudaram(venda, dados) and self._tem_paga(id):
            raise RegraNegocio(
                "Há parcelas pagas: as condições de pagamento não podem ser alteradas."
            )
        _aplicar_venda(venda, dados)
        self.db.commit()
        return venda_saida(venda), criado

    def remover(self, id: str) -> None:
        """Remove a venda com as parcelas."""
        venda = self._buscar(id)
        self.db.execute(sa.delete(m.Parcela).where(m.Parcela.venda_id == id))
        self.db.delete(venda)
        self.db.commit()

    def _buscar(self, id: str) -> m.Venda:
        venda = self.db.get(m.Venda, id)
        if venda is None:
            raise NaoEncontrado("Venda não encontrada.")
        return venda

    def _tem_paga(self, venda_id: str) -> bool:
        return (
            self.db.scalar(
                sa.select(m.Parcela.id).where(
                    m.Parcela.venda_id == venda_id,
                    m.Parcela.status == StatusParcela.paga,
                )
            )
            is not None
        )

    @staticmethod
    def _condicoes_mudaram(a: m.Venda, b: s.VendaEntrada) -> bool:
        p = b.plano
        return (
            a.forma_pagamento != b.forma_pagamento
            or a.valor_venda != b.valor_venda
            or a.valor_entrada != b.valor_entrada
            or a.vencimento_entrada != b.vencimento_entrada
            or a.plano_numero_parcelas != (p.numero_parcelas if p else None)
            or a.plano_taxa_juros_mes != (p.taxa_juros_mes if p else None)
            or a.plano_sistema != (p.sistema if p else None)
            or a.plano_primeiro_vencimento != (p.primeiro_vencimento if p else None)
        )

    def _validar(self, v: s.VendaEntrada) -> None:
        if not v.imovel_id:
            raise RegraNegocio("Selecione o imóvel.")
        if self.imoveis.obter(v.imovel_id) is None:
            raise RegraNegocio("Imóvel não encontrado.")
        if not v.compradores:
            raise RegraNegocio("Informe ao menos um comprador.")
        if v.valor_venda <= 0:
            raise RegraNegocio("Informe o valor da venda.")
        if v.valor_entrada > v.valor_venda:
            raise RegraNegocio("A entrada deve estar entre zero e o valor da venda.")
        self._soma_cem(v.vendedores, "vendedores")
        if any(p.contato_id is None for p in v.vendedores):
            raise RegraNegocio("Selecione todos os vendedores.")
        if any(p.contato_id in v.compradores for p in v.vendedores):
            raise RegraNegocio("Uma pessoa não pode ser compradora e vendedora.")
        if v.comissao_percentual > 0:
            self._soma_cem(v.corretores, "divisão da comissão")
        if v.forma_pagamento == FormaPagamento.financiamentoProprio:
            if v.plano is None or v.plano.numero_parcelas < 1:
                raise RegraNegocio("Informe a quantidade de parcelas.")
            if v.valor_venda - v.valor_entrada <= 0:
                raise RegraNegocio("Não há saldo a financiar.")
        pessoas = {*v.compradores, *(p.contato_id for p in v.vendedores + v.corretores)}
        for contato_id in pessoas - {None}:
            if not self.contatos.existe(contato_id):
                raise RegraNegocio("Contato da venda não encontrado.")

    @staticmethod
    def _soma_cem(ps: list[s.Participacao], nome: str) -> None:
        if not ps:
            raise RegraNegocio(f"Informe os {nome}.")
        soma = sum(p.percentual for p in ps)
        if abs(soma - 100) > 0.01:
            raise RegraNegocio(
                f"Os percentuais de {nome} somam {soma:.2f}%; devem somar 100%."
            )


# ------------------------------------------------------------------ Parcelas


class ParcelaService:
    def __init__(self, db: Session):
        self.db = db

    def listar(
        self, limite: int, deslocamento: int, *, venda_id=None, status=None
    ) -> Pagina[s.ParcelaSaida]:
        q = sa.select(m.Parcela)
        if venda_id:
            q = q.where(m.Parcela.venda_id == venda_id)
        if status:
            q = q.where(m.Parcela.status == status)
        total = self.db.scalar(sa.select(sa.func.count()).select_from(q.subquery())) or 0
        itens = self.db.scalars(
            q.order_by(m.Parcela.vencimento, m.Parcela.numero)
            .limit(limite)
            .offset(deslocamento)
        ).all()
        return pagina([parcela_saida(p) for p in itens], total, limite, deslocamento)

    def salvar(self, id: str, dados: s.ParcelaEntrada) -> tuple[s.ParcelaSaida, bool]:
        parcela, criado = self._gravar(id, dados)
        self.db.commit()
        return parcela_saida(parcela), criado

    def salvar_lote(self, lote: list[s.ParcelaLote]) -> list[s.ParcelaSaida]:
        """Grava várias parcelas numa só transação (tabela do financiamento)."""
        parcelas = [self._gravar(p.id, p)[0] for p in lote]
        self.db.commit()
        return [parcela_saida(p) for p in parcelas]

    def remover_da_venda(self, venda_id: str) -> None:
        self.db.execute(sa.delete(m.Parcela).where(m.Parcela.venda_id == venda_id))
        self.db.commit()

    def _gravar(self, id: str, dados: s.ParcelaEntrada) -> tuple[m.Parcela, bool]:
        id = validar_id(id)
        if self.db.get(m.Venda, dados.venda_id) is None:
            raise RegraNegocio("Venda não encontrada.")
        if dados.valor <= 0:
            raise RegraNegocio("Informe o valor da parcela.")
        parcela = self.db.get(m.Parcela, id)
        criado = parcela is None
        if criado:
            parcela = m.Parcela(id=id)
            self.db.add(parcela)
        for campo, valor in dados.model_dump(exclude={"id"}).items():
            setattr(parcela, campo, valor)
        return parcela, criado

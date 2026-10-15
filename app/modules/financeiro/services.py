"""Regras do Financeiro (equivalentes aos casos de uso do app). Encargos,
atualização monetária, fluxo de caixa e leitura do retorno bancário são
calculados no app; o servidor valida e guarda."""

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.errors import NaoEncontrado, RegraNegocio, validar_id
from app.core.schemas import Pagina, pagina
from app.core.sequencias import proximo_valor
from app.modules.crm.repositories import ContatoRepository
from app.modules.financeiro import models as m
from app.modules.financeiro import schemas as s
from app.modules.financeiro.enums import (
    IndiceMonetario,
    StatusBoleto,
    StatusLancamento,
    TipoLancamento,
)


def _paginar(db: Session, q: sa.Select, limite: int, deslocamento: int, saida):
    total = db.scalar(sa.select(sa.func.count()).select_from(q.subquery())) or 0
    itens = db.scalars(q.limit(limite).offset(deslocamento)).all()
    return pagina([saida.model_validate(i) for i in itens], total, limite, deslocamento)


def _gravar(db: Session, modelo, id: str, dados) -> tuple[object, bool]:
    obj = db.get(modelo, id)
    criado = obj is None
    if criado:
        obj = modelo(id=id)
        db.add(obj)
    for campo, valor in dados.model_dump(exclude={"id"}).items():
        setattr(obj, campo, valor)
    return obj, criado


# ---------------------------------------------------------- Contas bancárias


class ContaBancariaService:
    def __init__(self, db: Session):
        self.db = db

    def listar(self) -> list[s.ContaBancariaSaida]:
        q = sa.select(m.ContaBancaria).order_by(m.ContaBancaria.nome)
        return [s.ContaBancariaSaida.model_validate(c) for c in self.db.scalars(q)]

    def salvar(self, id: str, dados: s.ContaBancariaEntrada):
        if not dados.nome.strip():
            raise RegraNegocio("Informe o nome da conta.")
        conta, criado = _gravar(self.db, m.ContaBancaria, validar_id(id), dados)
        self.db.commit()
        return s.ContaBancariaSaida.model_validate(conta), criado

    def remover(self, id: str) -> None:
        conta = self.db.get(m.ContaBancaria, id)
        if conta is None:
            raise NaoEncontrado("Conta bancária não encontrada.")
        usada = any(
            self.db.scalar(sa.select(sa.func.count()).where(cond))
            for cond in (
                m.LinhaExtrato.conta_id == id,
                m.Lancamento.conta_baixa_id == id,
                m.Boleto.conta_id == id,
            )
        )
        if usada:
            raise RegraNegocio("A conta tem movimentações e não pode ser excluída.")
        self.db.delete(conta)
        self.db.commit()


# --------------------------------------------------------------- Lançamentos


class LancamentoService:
    def __init__(self, db: Session):
        self.db = db
        self.contatos = ContatoRepository(db)

    def listar(
        self, limite, deslocamento, *, tipo=None, status=None, contato_id=None,
        de=None, ate=None,
    ) -> Pagina[s.LancamentoSaida]:  # fmt: skip
        q = sa.select(m.Lancamento)
        if tipo:
            q = q.where(m.Lancamento.tipo == tipo)
        if status:
            q = q.where(m.Lancamento.status == status)
        if contato_id:
            q = q.where(m.Lancamento.contato_id == contato_id)
        if de:
            q = q.where(m.Lancamento.vencimento >= de)
        if ate:
            q = q.where(m.Lancamento.vencimento <= ate)
        q = q.order_by(m.Lancamento.vencimento, m.Lancamento.descricao)
        return _paginar(self.db, q, limite, deslocamento, s.LancamentoSaida)

    def obter(self, id: str) -> s.LancamentoSaida:
        return s.LancamentoSaida.model_validate(self._buscar(id))

    def salvar(self, id: str, dados: s.LancamentoEntrada):
        obj, criado = self._gravar(id, dados)
        self.db.commit()
        return s.LancamentoSaida.model_validate(obj), criado

    def salvar_lote(self, lote: list[s.LancamentoLote]) -> list[s.LancamentoSaida]:
        """Contas repetidas mês a mês, gravadas numa só transação."""
        objs = [self._gravar(item.id, item)[0] for item in lote]
        self.db.commit()
        return [s.LancamentoSaida.model_validate(o) for o in objs]

    def remover(self, id: str) -> None:
        lanc = self._buscar(id)
        if lanc.status == StatusLancamento.baixado:
            raise RegraNegocio("Estorne a baixa antes de excluir.")
        if self._boleto_emitido(id):
            raise RegraNegocio("Cancele o boleto emitido antes de excluir a conta.")
        self.db.execute(sa.delete(m.Boleto).where(m.Boleto.lancamento_id == id))
        self.db.delete(lanc)
        self.db.commit()

    def _buscar(self, id: str) -> m.Lancamento:
        lanc = self.db.get(m.Lancamento, id)
        if lanc is None:
            raise NaoEncontrado("Lançamento não encontrado.")
        return lanc

    def _boleto_emitido(self, lancamento_id: str) -> bool:
        return bool(
            self.db.scalar(
                sa.select(sa.func.count()).where(
                    m.Boleto.lancamento_id == lancamento_id,
                    m.Boleto.status == StatusBoleto.emitido,
                )
            )
        )

    def _gravar(self, id: str, d: s.LancamentoEntrada):
        id = validar_id(id)
        if not d.descricao.strip():
            raise RegraNegocio("Informe a descrição.")
        if d.valor <= 0:
            raise RegraNegocio("Informe o valor.")
        if d.multa_percentual < 0 or d.juros_mes_percentual < 0:
            raise RegraNegocio("Multa e juros não podem ser negativos.")
        if d.contato_id and not self.contatos.existe(d.contato_id):
            raise RegraNegocio("Cliente/fornecedor não encontrado.")
        if d.conta_baixa_id and self.db.get(m.ContaBancaria, d.conta_baixa_id) is None:
            raise RegraNegocio("Conta bancária não encontrada.")
        atual = self.db.get(m.Lancamento, id)
        if (
            atual is not None
            and atual.status == StatusLancamento.baixado
            and d.status != StatusLancamento.baixado
            and self.db.scalar(
                sa.select(m.LinhaExtrato.id).where(m.LinhaExtrato.lancamento_id == id)
            )
        ):
            raise RegraNegocio(
                "Esta baixa está conciliada com o extrato. Desfaça a conciliação primeiro."
            )
        return _gravar(self.db, m.Lancamento, id, d)


# ----------------------------------------------------------------- Extrato


class ExtratoService:
    def __init__(self, db: Session):
        self.db = db

    def listar(self, limite, deslocamento, *, conta_id=None, de=None, ate=None):
        q = sa.select(m.LinhaExtrato)
        if conta_id:
            q = q.where(m.LinhaExtrato.conta_id == conta_id)
        if de:
            q = q.where(m.LinhaExtrato.data >= de)
        if ate:
            q = q.where(m.LinhaExtrato.data <= ate)
        q = q.order_by(m.LinhaExtrato.data, m.LinhaExtrato.descricao)
        return _paginar(self.db, q, limite, deslocamento, s.LinhaExtratoSaida)

    def salvar(self, id: str, d: s.LinhaExtratoEntrada):
        id = validar_id(id)
        if self.db.get(m.ContaBancaria, d.conta_id) is None:
            raise RegraNegocio("Selecione a conta bancária.")
        if not d.descricao.strip():
            raise RegraNegocio("Informe a descrição.")
        if d.valor == 0:
            raise RegraNegocio("Informe o valor.")
        if d.lancamento_id:
            self._validar_conciliacao(id, d)
        linha, criado = _gravar(self.db, m.LinhaExtrato, id, d)
        self.db.commit()
        return s.LinhaExtratoSaida.model_validate(linha), criado

    def remover(self, id: str) -> None:
        linha = self.db.get(m.LinhaExtrato, id)
        if linha is None:
            raise NaoEncontrado("Linha do extrato não encontrada.")
        self.db.delete(linha)
        self.db.commit()

    def _validar_conciliacao(self, id: str, d: s.LinhaExtratoEntrada) -> None:
        lanc = self.db.get(m.Lancamento, d.lancamento_id)
        if lanc is None or lanc.status != StatusLancamento.baixado:
            raise RegraNegocio("Só contas baixadas podem ser conciliadas.")
        sinal = 1 if lanc.tipo == TipoLancamento.receber else -1
        if abs(d.valor - sinal * (lanc.valor_baixa or 0)) > 0.005:
            raise RegraNegocio("Os valores do extrato e da baixa são diferentes.")
        outra = self.db.scalar(
            sa.select(m.LinhaExtrato.id).where(
                m.LinhaExtrato.lancamento_id == d.lancamento_id,
                m.LinhaExtrato.id != id,
            )
        )
        if outra:
            raise RegraNegocio("Esta baixa já está conciliada com outra linha.")


# ------------------------------------------------------------------ Boletos


class BoletoService:
    def __init__(self, db: Session):
        self.db = db

    def listar(self, limite, deslocamento, *, status=None, lancamento_id=None):
        q = sa.select(m.Boleto)
        if status:
            q = q.where(m.Boleto.status == status)
        if lancamento_id:
            q = q.where(m.Boleto.lancamento_id == lancamento_id)
        q = q.order_by(m.Boleto.vencimento, m.Boleto.nosso_numero)
        return _paginar(self.db, q, limite, deslocamento, s.BoletoSaida)

    def salvar(self, id: str, d: s.BoletoEntrada):
        """Emite (nosso número sequencial por conta) ou atualiza o boleto."""
        id = validar_id(id)
        if self.db.get(m.ContaBancaria, d.conta_id) is None:
            raise RegraNegocio("Selecione a conta bancária.")
        lanc = self.db.get(m.Lancamento, d.lancamento_id)
        if lanc is None:
            raise RegraNegocio("Lançamento não encontrado.")
        boleto = self.db.get(m.Boleto, id)
        if boleto is None:
            self._validar_emissao(lanc)
        if not d.nosso_numero:
            seq = proximo_valor(self.db, f"nosso_numero_{d.conta_id}")
            d.nosso_numero = f"{seq:010d}"
        obj, criado = _gravar(self.db, m.Boleto, id, d)
        self.db.commit()
        return s.BoletoSaida.model_validate(obj), criado

    def _validar_emissao(self, lanc: m.Lancamento) -> None:
        if lanc.tipo != TipoLancamento.receber:
            raise RegraNegocio("Só contas a receber geram boleto.")
        if lanc.status != StatusLancamento.aberto:
            raise RegraNegocio("A conta não está em aberto.")
        if self.db.scalar(
            sa.select(sa.func.count()).where(
                m.Boleto.lancamento_id == lanc.id,
                m.Boleto.status == StatusBoleto.emitido,
            )
        ):
            raise RegraNegocio("Já existe um boleto em aberto para esta conta.")


# ------------------------------------------------- Índices e configuração


class IndiceService:
    def __init__(self, db: Session):
        self.db = db

    def listar(self) -> list[s.IndiceMensal]:
        q = sa.select(m.IndiceMensal).order_by(
            m.IndiceMensal.indice, m.IndiceMensal.ano, m.IndiceMensal.mes
        )
        return [s.IndiceMensal.model_validate(i) for i in self.db.scalars(q)]

    def salvar(self, d: s.IndiceMensal) -> s.IndiceMensal:
        if d.indice == IndiceMonetario.nenhum:
            raise RegraNegocio("Selecione o índice.")
        if not 1 <= d.mes <= 12:
            raise RegraNegocio("Mês inválido.")
        if not -50 <= d.percentual <= 100:
            raise RegraNegocio("Variação mensal fora do esperado.")
        obj = self.db.get(m.IndiceMensal, (d.indice, d.ano, d.mes))
        if obj is None:
            obj = m.IndiceMensal(indice=d.indice, ano=d.ano, mes=d.mes)
            self.db.add(obj)
        obj.percentual = d.percentual
        self.db.commit()
        return s.IndiceMensal.model_validate(obj)

    def remover(self, indice: IndiceMonetario, ano: int, mes: int) -> None:
        obj = self.db.get(m.IndiceMensal, (indice, ano, mes))
        if obj is not None:
            self.db.delete(obj)
            self.db.commit()


class ConfiguracaoService:
    def __init__(self, db: Session):
        self.db = db

    def obter(self) -> s.ConfiguracaoFinanceira:
        cfg = self.db.get(m.ConfiguracaoFinanceira, 1)
        return s.ConfiguracaoFinanceira.model_validate(cfg) if cfg else s.ConfiguracaoFinanceira()

    def salvar(self, d: s.ConfiguracaoFinanceira) -> s.ConfiguracaoFinanceira:
        if d.multa_percentual < 0 or d.juros_mes_percentual < 0:
            raise RegraNegocio("Multa e juros não podem ser negativos.")
        cfg = self.db.get(m.ConfiguracaoFinanceira, 1)
        if cfg is None:
            cfg = m.ConfiguracaoFinanceira(id=1)
            self.db.add(cfg)
        for campo, valor in d.model_dump().items():
            setattr(cfg, campo, valor)
        self.db.commit()
        return s.ConfiguracaoFinanceira.model_validate(cfg)

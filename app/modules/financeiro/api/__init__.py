from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.core.database import get_db
from app.core.schemas import Pagina
from app.modules.financeiro import schemas as s
from app.modules.financeiro.enums import (
    IndiceMonetario,
    StatusBoleto,
    StatusLancamento,
    TipoLancamento,
)
from app.modules.financeiro.services import (
    BoletoService,
    ContaBancariaService,
    ConfiguracaoService,
    ExtratoService,
    IndiceService,
    LancamentoService,
)

router = APIRouter(prefix="/financeiro")


def _svc(cls):
    return Annotated[cls, Depends(lambda db=Depends(get_db): cls(db))]


Contas = _svc(ContaBancariaService)
Lancamentos = _svc(LancamentoService)
Extrato = _svc(ExtratoService)
Boletos = _svc(BoletoService)
Indices = _svc(IndiceService)
Configuracao = _svc(ConfiguracaoService)
Limite = Annotated[int, Query(ge=1, le=500)]
Deslocamento = Annotated[int, Query(ge=0)]


def _criado(response: Response, criado: bool) -> None:
    if criado:
        response.status_code = status.HTTP_201_CREATED


# ---------------------------------------------------------- Contas bancárias
_t = ["Financeiro • Contas bancárias"]


@router.get("/contas-bancarias", tags=_t, response_model=list[s.ContaBancariaSaida])
def listar_contas(svc: Contas):
    return svc.listar()


@router.put("/contas-bancarias/{id}", tags=_t, response_model=s.ContaBancariaSaida)
def salvar_conta(id: str, dados: s.ContaBancariaEntrada, svc: Contas, response: Response):
    salvo, criado = svc.salvar(id, dados)
    _criado(response, criado)
    return salvo


@router.delete("/contas-bancarias/{id}", tags=_t, status_code=204)
def remover_conta(id: str, svc: Contas) -> None:
    """Recusa contas com extrato, baixas ou boletos."""
    svc.remover(id)


# --------------------------------------------------------------- Lançamentos
_t = ["Financeiro • Contas a pagar e a receber"]


@router.get("/lancamentos", tags=_t, response_model=Pagina[s.LancamentoSaida])
def listar_lancamentos(
    svc: Lancamentos,
    tipo: TipoLancamento | None = None,
    status_: StatusLancamento | None = Query(None, alias="status"),
    contato_id: str | None = Query(None, alias="contatoId"),
    de: date | None = Query(None, description="Vencimento a partir de"),
    ate: date | None = Query(None, description="Vencimento até"),
    limite: Limite = 100,
    deslocamento: Deslocamento = 0,
):
    return svc.listar(
        limite, deslocamento, tipo=tipo, status=status_, contato_id=contato_id,
        de=de, ate=ate,
    )  # fmt: skip


@router.put("/lancamentos", tags=_t, response_model=list[s.LancamentoSaida])
def salvar_lancamentos(lote: list[s.LancamentoLote], svc: Lancamentos):
    """Grava várias contas de uma vez (ex.: repetição mensal)."""
    return svc.salvar_lote(lote)


@router.get("/lancamentos/{id}", tags=_t, response_model=s.LancamentoSaida)
def obter_lancamento(id: str, svc: Lancamentos):
    return svc.obter(id)


@router.put("/lancamentos/{id}", tags=_t, response_model=s.LancamentoSaida)
def salvar_lancamento(
    id: str, dados: s.LancamentoEntrada, svc: Lancamentos, response: Response
):
    """Grava a conta, inclusive baixa e estorno (com encargos calculados no app)."""
    salvo, criado = svc.salvar(id, dados)
    _criado(response, criado)
    return salvo


@router.delete("/lancamentos/{id}", tags=_t, status_code=204)
def remover_lancamento(id: str, svc: Lancamentos) -> None:
    svc.remover(id)


# ----------------------------------------------------------------- Extrato
_t = ["Financeiro • Conciliação bancária"]


@router.get("/extrato", tags=_t, response_model=Pagina[s.LinhaExtratoSaida])
def listar_extrato(
    svc: Extrato,
    conta_id: str | None = Query(None, alias="contaId"),
    de: date | None = None,
    ate: date | None = None,
    limite: Limite = 100,
    deslocamento: Deslocamento = 0,
):
    return svc.listar(limite, deslocamento, conta_id=conta_id, de=de, ate=ate)


@router.put("/extrato/{id}", tags=_t, response_model=s.LinhaExtratoSaida)
def salvar_linha(id: str, dados: s.LinhaExtratoEntrada, svc: Extrato, response: Response):
    """Grava a linha; com `lancamentoId`, concilia com a baixa (mesmo valor)."""
    salvo, criado = svc.salvar(id, dados)
    _criado(response, criado)
    return salvo


@router.delete("/extrato/{id}", tags=_t, status_code=204)
def remover_linha(id: str, svc: Extrato) -> None:
    svc.remover(id)


# ------------------------------------------------------------------ Boletos
_t = ["Financeiro • Boletos"]


@router.get("/boletos", tags=_t, response_model=Pagina[s.BoletoSaida])
def listar_boletos(
    svc: Boletos,
    status_: StatusBoleto | None = Query(None, alias="status"),
    lancamento_id: str | None = Query(None, alias="lancamentoId"),
    limite: Limite = 100,
    deslocamento: Deslocamento = 0,
):
    return svc.listar(limite, deslocamento, status=status_, lancamento_id=lancamento_id)


@router.put("/boletos/{id}", tags=_t, response_model=s.BoletoSaida)
def salvar_boleto(id: str, dados: s.BoletoEntrada, svc: Boletos, response: Response):
    """Emite (nosso número vazio = próximo da conta) ou atualiza o boleto."""
    salvo, criado = svc.salvar(id, dados)
    _criado(response, criado)
    return salvo


# ------------------------------------------------- Índices e configuração
_t = ["Financeiro • Juros, multa e correção"]


@router.get("/indices", tags=_t, response_model=list[s.IndiceMensal])
def listar_indices(svc: Indices):
    return svc.listar()


@router.put("/indices", tags=_t, response_model=s.IndiceMensal)
def salvar_indice(dados: s.IndiceMensal, svc: Indices):
    """Grava a variação do mês (substitui se já existir)."""
    return svc.salvar(dados)


@router.delete("/indices/{indice}/{ano}/{mes}", tags=_t, status_code=204)
def remover_indice(indice: IndiceMonetario, ano: int, mes: int, svc: Indices) -> None:
    svc.remover(indice, ano, mes)


@router.get("/configuracao", tags=_t, response_model=s.ConfiguracaoFinanceira)
def obter_configuracao(svc: Configuracao):
    return svc.obter()


@router.put("/configuracao", tags=_t, response_model=s.ConfiguracaoFinanceira)
def salvar_configuracao(dados: s.ConfiguracaoFinanceira, svc: Configuracao):
    return svc.salvar(dados)


# ------------------------------------------------------ Pastas e documentos
from app.modules.financeiro.api import documentos as _documentos  # noqa: E402

router.include_router(_documentos.router)

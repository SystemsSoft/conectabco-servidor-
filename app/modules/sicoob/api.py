"""Integração Sicoob (testes no Sandbox): configuração, boletos, Pix,
conta corrente e o registro de cada chamada feita ao banco."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.auth import UsuarioLogado
from app.core.database import get_db
from app.core.errors import NaoEncontrado
from app.core.schemas import Esquema
from app.modules.sicoob import schemas as s
from app.modules.sicoob import services as svc
from app.modules.sicoob.models import ChamadaSicoob

router = APIRouter(prefix="/integracoes/sicoob", tags=["Integração Sicoob"])
Db = Annotated[Session, Depends(get_db)]


class BoletoRegistrado(Esquema):
    boleto: s.BoletoSaida
    pdf: str = ""


@router.get("/configuracao", response_model=s.ConfiguracaoSaida)
def obter_configuracao(db: Db):
    return svc.configuracao(db)


@router.put("/configuracao", response_model=s.ConfiguracaoSaida)
def salvar_configuracao(dados: s.ConfiguracaoEntrada, db: Db):
    return svc.salvar_configuracao(db, dados)


@router.post("/testar", response_model=list[s.ResultadoTeste])
def testar(db: Db, usuario: UsuarioLogado):
    return svc.testar(db, usuario.id)


@router.get("/cobrancas-abertas", response_model=list[s.CobrancaAberta])
def cobrancas_abertas(db: Db):
    """Cobranças do aluguel em aberto (para gerar boleto ou Pix de teste)."""
    return svc.cobrancas_abertas(db)


@router.get("/rascunho", response_model=s.Rascunho)
def rascunho(db: Db, cobranca_id: str = Query(alias="cobrancaId")):
    return svc.rascunho(db, cobranca_id)


# Boletos
@router.get("/boletos", response_model=list[s.BoletoSaida])
def listar_boletos(db: Db):
    return svc.boletos(db)


@router.post("/boletos", response_model=BoletoRegistrado, status_code=201)
def registrar_boleto(dados: s.BoletoEntrada, db: Db, usuario: UsuarioLogado):
    boleto, pdf = svc.registrar_boleto(db, dados, usuario.id)
    return BoletoRegistrado(boleto=boleto, pdf=pdf)


@router.post("/boletos/{id}/consultar", response_model=s.BoletoSaida)
def consultar_boleto(id: str, db: Db, usuario: UsuarioLogado):
    return svc.consultar_boleto(db, id, usuario.id)


class PdfBoleto(Esquema):
    pdf: str  # base64


@router.get("/boletos/{id}/pdf", response_model=PdfBoleto)
def pdf_boleto(id: str, db: Db, usuario: UsuarioLogado):
    """Segunda via do boleto (PDF em base64)."""
    import base64

    return PdfBoleto(pdf=base64.b64encode(svc.pdf_boleto(db, id, usuario.id)).decode())


@router.post("/boletos/{id}/baixar", response_model=s.BoletoSaida)
def baixar_boleto(id: str, db: Db, usuario: UsuarioLogado):
    return svc.baixar_boleto(db, id, usuario.id)


# Pix
@router.get("/pix", response_model=list[s.PixSaida])
def listar_pix(db: Db):
    return svc.cobrancas_pix(db)


@router.post("/pix", response_model=s.PixSaida, status_code=201)
def criar_pix(dados: s.PixEntrada, db: Db, usuario: UsuarioLogado):
    return svc.criar_pix(db, dados, usuario.id)


@router.post("/pix/{id}/consultar", response_model=s.PixSaida)
def consultar_pix(id: str, db: Db, usuario: UsuarioLogado):
    return svc.consultar_pix(db, id, usuario.id)


@router.get("/pix-recebidos", response_model=list[s.PixRecebido])
def pix_recebidos(db: Db, usuario: UsuarioLogado, inicio: date, fim: date):
    return svc.pix_recebidos(db, inicio, fim, usuario.id)


# Conta corrente
@router.get("/saldo", response_model=s.Saldo)
def saldo(db: Db, usuario: UsuarioLogado):
    return svc.saldo(db, usuario.id)


@router.get("/extrato", response_model=s.Extrato)
def extrato(db: Db, usuario: UsuarioLogado,
            mes: Annotated[int, Query(ge=1, le=12)], ano: Annotated[int, Query(ge=2000, le=2100)]):  # fmt: skip
    return svc.extrato(db, mes, ano, usuario.id)


@router.post("/extrato/importar", response_model=s.ResultadoImportacao)
def importar_extrato(dados: s.ImportacaoExtrato, db: Db, usuario: UsuarioLogado):
    """Leva o extrato do mês para a Conciliação bancária do Financeiro."""
    return svc.importar_extrato(db, dados.mes, dados.ano, usuario.id)


# Registro de chamadas
@router.get("/chamadas", response_model=list[s.Chamada])
def listar_chamadas(db: Db):
    return [s.Chamada.model_validate(c, from_attributes=True) for c in svc.chamadas(db)]


@router.get("/chamadas/{id}", response_model=s.ChamadaDetalhe)
def obter_chamada(id: str, db: Db):
    c = db.get(ChamadaSicoob, id)
    if c is None:
        raise NaoEncontrado("Chamada não encontrada.")
    return s.ChamadaDetalhe.model_validate(c, from_attributes=True)

"""Área do proprietário: acesso, imóveis/contratos em que ele é
beneficiário, repasses (mesmo cálculo da gestão), auditorias publicadas e
manutenções. Tudo lido das tabelas da gestão."""

import math
from dataclasses import dataclass
from datetime import date

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core import acesso_portal as portal
from app.core.errors import NaoEncontrado, RegraNegocio
from app.modules.auditoria import models as aud
from app.modules.auditoria.enums import StatusAuditoria
from app.modules.crm.enums import TipoPessoa
from app.modules.crm.models import Contato, Imovel
from app.modules.locacao import models as loc
from app.modules.locacao.enums import (
    NaturezaDespesa,
    ResponsavelDespesa,
    StatusCobranca,
    StatusContrato,
    TipoItemCobranca,
)
from app.modules.manutencao.models import Manutencao
from app.modules.proprietario.models import AcessoProprietario as Acesso

TIPO = "proprietario"


# ------------------------------------------------------------------ Acesso


def liberar_acesso(db: Session, contato_id: str) -> tuple[Acesso, str]:
    contato = portal.obter_contato(db, contato_id)
    portal.exigir_documento(contato, "proprietário")
    if not contratos_do(db, contato_id):
        raise RegraNegocio("Este contato não é proprietário (beneficiário) de nenhum contrato.")
    return portal.liberar(db, Acesso, contato, "proprietário")


def revogar_acesso(db: Session, contato_id: str) -> None:
    portal.revogar(db, Acesso, contato_id)


def acessos_por_contato(db: Session) -> dict[str, Acesso]:
    return {a.contato_id: a for a in db.scalars(sa.select(Acesso))}


def autenticar(db: Session, login: str, senha: str) -> Acesso:
    return portal.autenticar(db, Acesso, login, senha)


def trocar_senha(db: Session, acesso: Acesso, atual: str, nova: str, repetida: str) -> None:
    portal.trocar_senha(db, acesso, atual, nova, repetida)


def criar_token(acesso: Acesso) -> str:
    return portal.criar_token(acesso, TIPO)


def acesso_do_token(db: Session, token: str | None) -> Acesso | None:
    return portal.acesso_do_token(db, Acesso, token, TIPO)


def token_csrf(acesso: Acesso) -> str:
    return portal.token_csrf(acesso, TIPO)


# --------------------------------------------------------------- Imóveis


def contratos_do(db: Session, contato_id: str) -> list[loc.ContratoLocacao]:
    """Contratos em que o contato é beneficiário (ativos primeiro)."""
    contratos = db.scalars(
        sa.select(loc.ContratoLocacao)
        .join(loc.Beneficiario, loc.Beneficiario.contrato_id == loc.ContratoLocacao.id)
        .where(loc.Beneficiario.contato_id == contato_id)
        .order_by(loc.ContratoLocacao.data_inicio.desc())
    ).unique().all()
    return sorted(contratos, key=lambda c: c.status != StatusContrato.ativo)


def imoveis_do(db: Session, contato_id: str) -> list[Imovel]:
    ids = {c.imovel_id for c in contratos_do(db, contato_id)}
    ids |= set(db.scalars(sa.select(Imovel.id).where(Imovel.proprietario_id == contato_id)))
    return [db.get(Imovel, i) for i in sorted(ids)]


def cota(contrato: loc.ContratoLocacao, contato_id: str) -> float:
    return next((b.percentual for b in contrato.beneficiarios if b.contato_id == contato_id), 0) / 100


# --------------------------------------------------------------- Repasses
# Mesmo cálculo da gestão (CalcularRepasse no app).

_FAIXAS_IR = [(2428.80, 0, 0), (2826.65, .075, 182.16), (3751.05, .15, 394.16),
              (4664.68, .225, 675.49), (math.inf, .275, 908.73)]  # fmt: skip


def _arred(v: float) -> float:
    return round(v + 1e-9, 2)


def imposto_mensal(base: float, ano: int) -> float:
    if base <= 0:
        return 0
    limite, aliquota, deducao = next(f for f in _FAIXAS_IR if base <= f[0])
    imposto = max(0, base * aliquota - deducao)
    if ano >= 2026:  # Lei nº 15.270/2025: redução até R$ 7.350,00
        if base <= 5000:
            redutor = imposto
        elif base <= 7350:
            redutor = min(imposto, max(0, 978.62 - 0.133145 * base))
        else:
            redutor = 0
        imposto -= redutor
    return _arred(max(0, imposto))


def _incide(d: loc.Despesa, competencia: date) -> bool:
    c, ini = competencia.replace(day=1), d.competencia_inicio.replace(day=1)
    if d.natureza == NaturezaDespesa.extraordinaria:
        return c == ini
    if c < ini:
        return False
    return d.competencia_fim is None or c <= d.competencia_fim.replace(day=1)


@dataclass
class LinhaRepasse:
    cobranca: loc.Cobranca
    contrato: loc.ContratoLocacao
    aluguel: float
    encargos: float
    taxa_administracao: float
    taxa_intermediacao: float
    despesas: float
    irrf: float
    repassado_em: date | None

    @property
    def bruto(self) -> float:
        return self.aluguel + self.encargos

    @property
    def liquido(self) -> float:
        return _arred(self.bruto - self.taxa_administracao - self.taxa_intermediacao - self.despesas - self.irrf)


def repasses(db: Session, contato_id: str, ano: int | None = None) -> list[LinhaRepasse]:
    contatos: dict[str, Contato] = {}

    def pj(contato_id: str) -> bool:
        c = contatos.get(contato_id) or db.get(Contato, contato_id)
        contatos[contato_id] = c
        return bool(c and c.tipo_pessoa == TipoPessoa.juridica)

    linhas = []
    for c in contratos_do(db, contato_id):
        participacao = cota(c, contato_id)
        despesas = list(db.scalars(sa.select(loc.Despesa).where(
            loc.Despesa.contrato_id == c.id,
            loc.Despesa.responsavel == ResponsavelDespesa.proprietario,
        )))  # fmt: skip
        repassados = dict(db.execute(sa.select(loc.RepasseRealizado.cobranca_id, loc.RepasseRealizado.data).where(
            loc.RepasseRealizado.contato_id == contato_id
        )).all())  # fmt: skip
        cobrancas = db.scalars(sa.select(loc.Cobranca).where(
            loc.Cobranca.contrato_id == c.id, loc.Cobranca.status == StatusCobranca.paga
        )).all()  # fmt: skip
        for cb in cobrancas:
            if ano and cb.competencia.year != ano:
                continue
            doc = [d for d in despesas if _incide(d, cb.competencia)]
            total_desp = sum(d.valor for d in doc)
            dedutiveis = sum(d.valor for d in doc if d.dedutivel_ir)
            valor_aluguel = sum(i.valor for i in cb.itens if i.tipo == TipoItemCobranca.aluguel)
            encargos = cb.multa + cb.juros - cb.desconto
            primeira = cb.competencia.replace(day=1) == c.data_inicio.replace(day=1)
            intermediacao = valor_aluguel * c.taxa_intermediacao / 100 if primeira else 0
            aluguel = _arred(valor_aluguel * participacao)
            enc = _arred(encargos * participacao)
            taxa_adm = _arred((aluguel + enc) * c.taxa_administracao / 100)
            base = _arred(max(0, aluguel + enc - taxa_adm - _arred(dedutiveis * participacao)))
            retem = pj(c.locatario_id) and not pj(contato_id)
            ano_ir = (cb.data_pagamento or cb.competencia).year
            linhas.append(LinhaRepasse(
                cobranca=cb, contrato=c, aluguel=aluguel, encargos=enc, taxa_administracao=taxa_adm,
                taxa_intermediacao=_arred(intermediacao * participacao),
                despesas=_arred(total_desp * participacao),
                irrf=imposto_mensal(base, ano_ir) if retem else 0,
                repassado_em=repassados.get(cb.id),
            ))  # fmt: skip
    return sorted(linhas, key=lambda x: (x.cobranca.competencia, x.contrato.numero), reverse=True)


# ------------------------------------------------- Auditorias e manutenções


def _do_proprietario(db: Session, contato_id: str):
    contratos = {c.id for c in contratos_do(db, contato_id)}
    imoveis = {i.id for i in imoveis_do(db, contato_id)}
    return contratos, imoveis


def auditorias_publicadas(db: Session, contato_id: str) -> list[aud.Auditoria]:
    contratos, imoveis = _do_proprietario(db, contato_id)
    return list(db.scalars(
        sa.select(aud.Auditoria).where(
            aud.Auditoria.publicada.is_(True),
            aud.Auditoria.status == StatusAuditoria.concluida,
            sa.or_(aud.Auditoria.proprietario_id == contato_id,
                   aud.Auditoria.contrato_id.in_(contratos),
                   aud.Auditoria.imovel_id.in_(imoveis)),
        ).order_by(aud.Auditoria.data_realizada.desc())
    ))  # fmt: skip


def auditoria_publicada(db: Session, contato_id: str, id_: str) -> aud.Auditoria:
    for a in auditorias_publicadas(db, contato_id):
        if a.id == id_:
            return a
    raise NaoEncontrado("Auditoria não encontrada.")


def midia_publicada(db: Session, contato_id: str, midia_id: str) -> aud.MidiaAuditoria:
    midia = db.get(aud.MidiaAuditoria, midia_id)
    if midia is None:
        raise NaoEncontrado("Arquivo não encontrado.")
    auditoria_publicada(db, contato_id, midia.auditoria_id)  # confere o acesso
    return midia


def manutencoes(db: Session, contato_id: str) -> list[Manutencao]:
    _, imoveis = _do_proprietario(db, contato_id)
    return list(db.scalars(
        sa.select(Manutencao).where(Manutencao.imovel_id.in_(imoveis))
        .order_by(Manutencao.criado_em.desc())
    ))  # fmt: skip

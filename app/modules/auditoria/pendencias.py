"""Auditoria automática: confere os dados que o sistema já tem e aponta o
que está errado ou atrasado, por contrato e proprietário. Calculada na hora
(nada é gravado): resolveu na gestão, some daqui."""

import calendar
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.tempo import agora
from app.modules.auditoria import models as m
from app.modules.auditoria import schemas as s
from app.modules.auditoria.enums import AreaPendencia as A
from app.modules.auditoria.enums import Gravidade as G
from app.modules.auditoria.enums import StatusAuditoria
from app.modules.crm.enums import PapelContato
from app.modules.crm.models import Contato, Imovel
from app.modules.inquilino.enums import TipoArquivoContrato
from app.modules.inquilino.models import ArquivoContrato
from app.modules.locacao import models as loc
from app.modules.locacao.enums import GarantiaLocacao, StatusCobranca, StatusContrato
from app.modules.manutencao.enums import OrigemManutencao, StatusManutencao
from app.modules.manutencao.models import Manutencao


def somar_meses(d: date, meses: int) -> date:
    total = d.month - 1 + meses
    ano, mes = d.year + total // 12, total % 12 + 1
    return date(ano, mes, min(d.day, calendar.monthrange(ano, mes)[1]))


def _br(d: date) -> str:
    return d.strftime("%d/%m/%Y")


def _competencia(d: date) -> str:
    return d.strftime("%m/%Y")


@dataclass
class Dados:
    """Tudo o que as regras usam, carregado de uma vez."""

    contratos: list[loc.ContratoLocacao]
    imoveis: dict[str, Imovel]
    contatos: dict[str, Contato]
    cobrancas: dict[str, list[loc.Cobranca]]
    repassados: set[tuple[str, str]]
    manutencoes: dict[str, list[Manutencao]]
    arquivos: dict[str, set[TipoArquivoContrato]]
    auditorias: dict[str, list[m.Auditoria]]
    cfg: s.ConfiguracaoAuditoria
    hoje: date = field(default_factory=lambda: agora().date())
    momento: datetime = field(default_factory=agora)


def carregar(db: Session, cfg: s.ConfiguracaoAuditoria) -> Dados:
    contratos = list(db.scalars(sa.select(loc.ContratoLocacao)))
    cobrancas: dict[str, list] = defaultdict(list)
    for c in db.scalars(sa.select(loc.Cobranca)):
        cobrancas[c.contrato_id].append(c)
    manutencoes: dict[str, list] = defaultdict(list)
    for mt in db.scalars(sa.select(Manutencao)):
        manutencoes[mt.imovel_id].append(mt)
    arquivos: dict[str, set] = defaultdict(set)
    for contrato_id, tipo in db.execute(sa.select(ArquivoContrato.contrato_id, ArquivoContrato.tipo)):
        arquivos[contrato_id].add(tipo)
    auditorias: dict[str, list] = defaultdict(list)
    for a in db.scalars(sa.select(m.Auditoria)):
        auditorias[a.imovel_id].append(a)
    return Dados(
        contratos=contratos,
        imoveis={i.id: i for i in db.scalars(sa.select(Imovel))},
        contatos={c.id: c for c in db.scalars(sa.select(Contato))},
        cobrancas=cobrancas,
        repassados=set(db.execute(
            sa.select(loc.RepasseRealizado.cobranca_id, loc.RepasseRealizado.contato_id)
        ).all()),  # fmt: skip
        manutencoes=manutencoes,
        arquivos=arquivos,
        auditorias=auditorias,
        cfg=cfg,
    )


def _donos(c: loc.ContratoLocacao) -> list[str]:
    return [b.contato_id for b in c.beneficiarios]


def pendencias(d: Dados) -> list[s.Pendencia]:
    """Regras por contrato ativo; cada achado vale para cada proprietário
    (beneficiário) do contrato."""
    achados: list[s.Pendencia] = []
    imoveis_vistos: set[str] = set()

    def add(regra, ref, gravidade, area, titulo, detalhe, contrato, donos=None):
        for dono in donos if donos is not None else _donos(contrato):
            achados.append(s.Pendencia(
                id=f"{regra}:{ref}:{dono}", gravidade=gravidade, area=area,
                titulo=titulo, detalhe=detalhe, contrato_id=contrato.id,
                imovel_id=contrato.imovel_id, proprietario_id=dono,
            ))  # fmt: skip

    for c in d.contratos:
        if c.status != StatusContrato.ativo:
            continue
        imovel = d.imoveis.get(c.imovel_id)
        nome = f"{c.numero} – {imovel.titulo if imovel else ''}"
        cfg, hoje = d.cfg, d.hoje

        # Financeiro: repasses, atrasos e cobrança do mês.
        for cb in d.cobrancas.get(c.id, []):
            if cb.status == StatusCobranca.paga and cb.data_pagamento:
                dias = (hoje - cb.data_pagamento).days
                if dias > cfg.prazo_repasse_dias:
                    for dono in _donos(c):
                        if (cb.id, dono) not in d.repassados:
                            add("repasse", cb.id, G.critica if dias > 2 * cfg.prazo_repasse_dias else G.atencao,
                                A.financeiro, f"Repasse pendente – {_competencia(cb.competencia)}",
                                f"{nome}: aluguel pago em {_br(cb.data_pagamento)} e ainda não repassado ({dias} dias).",
                                c, [dono])  # fmt: skip
            elif cb.status == StatusCobranca.aberta and cb.vencimento < hoje:
                dias = (hoje - cb.vencimento).days
                add("atraso", cb.id, G.critica if dias > cfg.atraso_critico_dias else G.atencao,
                    A.financeiro, f"Aluguel em atraso há {dias} dia{'s' if dias != 1 else ''}",
                    f"{nome}: competência {_competencia(cb.competencia)}, vencida em {_br(cb.vencimento)}.", c)  # fmt: skip
        mes_atual = hoje.replace(day=1)
        if (c.data_inicio <= hoje and c.data_inicio.replace(day=1) <= mes_atual
                and hoje.day >= max(1, c.dia_vencimento - 5)
                and not any(cb.competencia.replace(day=1) == mes_atual for cb in d.cobrancas.get(c.id, []))):  # fmt: skip
            add("sem-cobranca", f"{c.id}:{mes_atual}", G.atencao, A.financeiro,
                f"Cobrança de {_competencia(mes_atual)} não gerada",
                f"{nome}: vence todo dia {c.dia_vencimento}.", c)  # fmt: skip

        # Contrato: vigência, reajuste e garantia.
        fim = somar_meses(c.data_inicio, c.prazo_meses)
        if fim < hoje:
            add("vencido", c.id, G.critica, A.contrato, "Contrato vencido e ainda ativo",
                f"{nome}: terminou em {_br(fim)}. Renove ou encerre.", c)  # fmt: skip
        elif (fim - hoje).days <= cfg.aviso_vencimento_contrato_dias:
            add("vence", c.id, G.atencao, A.contrato, f"Contrato vence em {_br(fim)}",
                f"{nome}: combine a renovação com inquilino e proprietário.", c)  # fmt: skip
        anos = 1
        while (aniv := somar_meses(c.data_inicio, 12 * anos)) <= hoje:
            if (hoje - aniv).days <= 60:
                add("reajuste", f"{c.id}:{aniv}", G.info, A.contrato, f"Aniversário do contrato em {_br(aniv)}",
                    f"{nome}: confira se o reajuste pelo {c.indice_reajuste.rotulo} foi aplicado.", c)  # fmt: skip
            anos += 1
        if c.garantia == GarantiaLocacao.fiador and not c.fiador_id:
            add("fiador", c.id, G.atencao, A.contrato, "Garantia por fiador sem fiador cadastrado", nome, c)
        elif c.garantia == GarantiaLocacao.semGarantia:
            add("sem-garantia", c.id, G.info, A.contrato, "Contrato sem garantia", nome, c)

        # Documentos no portal do inquilino.
        tipos = d.arquivos.get(c.id, set())
        if TipoArquivoContrato.vistoria not in tipos:
            add("sem-vistoria", c.id, G.atencao, A.documentos, "Laudo de vistoria não publicado",
                f"{nome}: publique em Locação › Portal do inquilino.", c)  # fmt: skip
        if TipoArquivoContrato.contrato not in tipos:
            add("sem-via", c.id, G.info, A.documentos, "Via digital do contrato não publicada", nome, c)

        # Imóvel: manutenções, chamados e auditoria em campo.
        if c.imovel_id not in imoveis_vistos:
            imoveis_vistos.add(c.imovel_id)
            for mt in d.manutencoes.get(c.imovel_id, []):
                if mt.status == StatusManutencao.concluida:
                    continue
                horas = (d.momento - mt.criado_em).total_seconds() / 3600
                if (mt.origem == OrigemManutencao.inquilino and mt.status == StatusManutencao.pendente
                        and horas > cfg.chamado_sem_resposta_horas):  # fmt: skip
                    add("chamado", mt.id, G.critica, A.imovel, "Chamado do inquilino sem resposta",
                        f"{nome}: \"{mt.descricao[:80]}\" aberto em {_br(mt.criado_em.date())}.", c)  # fmt: skip
                elif horas / 24 > cfg.manutencao_parada_dias:
                    add("manutencao", mt.id, G.atencao, A.imovel,
                        f"Manutenção parada há {int(horas // 24)} dias",
                        f"{nome}: {mt.descricao[:100]}", c)  # fmt: skip
            auditorias = d.auditorias.get(c.imovel_id, [])
            concluidas = [a.data_realizada for a in auditorias
                          if a.status == StatusAuditoria.concluida and a.data_realizada]  # fmt: skip
            ultima = max(concluidas, default=None)
            limite = somar_meses(hoje, -cfg.meses_sem_auditoria)
            if ultima is None and c.data_inicio <= somar_meses(hoje, -3):
                add("sem-auditoria", c.imovel_id, G.atencao, A.imovel, "Imóvel nunca auditado em campo",
                    f"{nome}: agende uma auditoria.", c)  # fmt: skip
            elif ultima and ultima < limite:
                add("auditoria-antiga", c.imovel_id, G.atencao, A.imovel,
                    f"Última auditoria em {_br(ultima)}", f"{nome}: agende uma nova auditoria.", c)  # fmt: skip
            for a in auditorias:
                if a.status == StatusAuditoria.agendada and a.data_agendada and a.data_agendada < hoje:
                    add("auditoria-atrasada", a.id, G.atencao, A.imovel,
                        f"Auditoria {a.numero} agendada para {_br(a.data_agendada)} não realizada", nome, c)  # fmt: skip

    # Cadastro dos proprietários (repasse e DIMOB).
    donos = {dono for c in d.contratos if c.status == StatusContrato.ativo for dono in _donos(c)}
    for dono in donos:
        p = d.contatos.get(dono)
        if p is None:
            continue
        contrato = next(c for c in d.contratos if c.status == StatusContrato.ativo and dono in _donos(c))
        if len("".join(ch for ch in p.documento if ch.isdigit())) not in (11, 14):
            add("cpf", dono, G.atencao, A.cadastro, "Proprietário sem CPF/CNPJ",
                f"{p.nome}: necessário para a DIMOB e o informe de rendimentos.", contrato, [dono])  # fmt: skip
        if not p.pix and not p.conta:
            add("banco", dono, G.atencao, A.cadastro, "Proprietário sem dados para repasse",
                f"{p.nome}: cadastre PIX ou conta bancária.", contrato, [dono])  # fmt: skip

    ordem = {G.critica: 0, G.atencao: 1, G.info: 2}
    return sorted(achados, key=lambda p: (ordem[p.gravidade], p.area.value, p.titulo))


def proprietarios(d: Dados, lista: list[s.Pendencia], acessos: dict) -> list[s.ResumoProprietario]:
    """Visão consolidada por proprietário: beneficiários de contratos e,
    sem números, quem tem o perfil Proprietário, imóvel em seu nome ou acesso
    à Área do proprietário (o acesso só exige o CPF/CNPJ)."""
    por_dono: dict[str, list[loc.ContratoLocacao]] = defaultdict(list)
    for c in d.contratos:
        for dono in _donos(c):
            por_dono[dono].append(c)
    resumo = []
    for dono, contratos in por_dono.items():
        p = d.contatos.get(dono)
        if p is None:
            continue
        ativos = [c for c in contratos if c.status == StatusContrato.ativo]
        minhas = [x for x in lista if x.proprietario_id == dono]
        criticas = sum(x.gravidade == G.critica for x in minhas)
        atencoes = sum(x.gravidade == G.atencao for x in minhas)
        cota = {c.id: next(b.percentual for b in c.beneficiarios if b.contato_id == dono) / 100 for c in contratos}
        em_atraso = sum(
            sum(i.valor for i in cb.itens) * cota[c.id]
            for c in ativos for cb in d.cobrancas.get(c.id, [])
            if cb.status == StatusCobranca.aberta and cb.vencimento < d.hoje
        )
        datas = [a.data_realizada for c in contratos for a in d.auditorias.get(c.imovel_id, [])
                 if a.status == StatusAuditoria.concluida and a.data_realizada]  # fmt: skip
        acesso = acessos.get(dono)
        resumo.append(s.ResumoProprietario(
            contato_id=dono, nome=p.nome, documento=p.documento,
            imoveis=len({c.imovel_id for c in contratos}), contratos_ativos=len(ativos),
            aluguel_mensal=round(sum(c.valor_aluguel * cota[c.id] for c in ativos), 2),
            em_atraso=round(em_atraso, 2), criticas=criticas, atencoes=atencoes,
            ultima_auditoria=max(datas, default=None),
            saude="vermelho" if criticas else "amarelo" if atencoes else "verde",
            acesso=_acesso(acesso, d) if acesso else None,
        ))  # fmt: skip
    com_contrato = set(por_dono)
    sem_contrato = (
        {c.id for c in d.contatos.values() if any(x.papel == PapelContato.proprietario for x in c.papeis)}
        | {i.proprietario_id for i in d.imoveis.values() if i.proprietario_id}
        | set(acessos)
    ) - com_contrato
    for dono in sem_contrato:
        p = d.contatos.get(dono)
        if p is None:
            continue
        acesso = acessos.get(dono)
        resumo.append(s.ResumoProprietario(
            contato_id=dono, nome=p.nome, documento=p.documento,
            imoveis=sum(i.proprietario_id == dono for i in d.imoveis.values()),
            contratos_ativos=0, aluguel_mensal=0, em_atraso=0, criticas=0, atencoes=0,
            ultima_auditoria=None, saude="verde",
            acesso=_acesso(acesso, d) if acesso else None,
        ))  # fmt: skip
    return sorted(resumo, key=lambda r: ({"vermelho": 0, "amarelo": 1, "verde": 2}[r.saude], r.nome))


def _acesso(acesso, d: Dados) -> s.AcessoPortal:
    return s.AcessoPortal(
        ativo=acesso.ativo, trocar_senha=acesso.trocar_senha,
        bloqueado=bool(acesso.bloqueado_ate and acesso.bloqueado_ate > d.momento),
        ultimo_acesso=acesso.ultimo_acesso,
    )


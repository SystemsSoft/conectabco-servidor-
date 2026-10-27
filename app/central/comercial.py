"""Comercial da plataforma: funil das solicitações de implantação, desempenho
dos representantes, receita recorrente das imobiliárias e os leads do
pré-cadastro do site."""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.central import models as m
from app.core.errors import NaoEncontrado, RegraNegocio
from app.core.tempo import agora

PERIODOS = {"mes": "Este mês", "3m": "Últimos 3 meses", "12m": "Últimos 12 meses", "tudo": "Todo o período"}
SITUACOES_LEAD = {"novo": "Novo", "em_contato": "Em contato", "convertido": "Convertido", "descartado": "Descartado"}
SEM_ENVIO_DIAS = 30
MESES = ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez")


def inicio_do_periodo(periodo: str, hoje: date | None = None) -> datetime | None:
    hoje = hoje or agora().date()
    primeiro = hoje.replace(day=1)
    if periodo == "mes":
        return datetime.combine(primeiro, datetime.min.time())
    if periodo in ("3m", "12m"):
        meses = 2 if periodo == "3m" else 11
        ano, mes = divmod(primeiro.year * 12 + primeiro.month - 1 - meses, 12)
        return datetime(ano, mes + 1, 1)
    return None


def _taxa(parte: int, todo: int) -> int | None:
    return round(100 * parte / todo) if todo else None


def _media_dias(intervalos: list[timedelta]) -> float | None:
    if not intervalos:
        return None
    return round(sum(i.total_seconds() for i in intervalos) / len(intervalos) / 86400, 1)


# ------------------------------------------------------------------ Funil


@dataclass
class Funil:
    entradas: int = 0
    pagas: int = 0
    em_implantacao: int = 0  # em implantação ou já implantadas
    implantadas: int = 0
    recusadas: int = 0
    aguardando: int = 0
    dias_ate_pagamento: float | None = None
    dias_ate_implantacao: float | None = None
    dias_total: float | None = None
    etapas: list[dict] = field(default_factory=list)


def funil(db: Session, inicio: datetime | None) -> Funil:
    """Solicitações que entraram no período, contadas pela etapa que já alcançaram."""
    s = m.SolicitacaoImplantacao
    consulta = sa.select(s)
    if inicio:
        consulta = consulta.where(s.criada_em >= inicio)
    lista = list(db.scalars(consulta))
    f = Funil(entradas=len(lista))
    f.pagas = sum(x.pago for x in lista)
    f.em_implantacao = sum(x.situacao in ("em_andamento", "implantada") for x in lista)
    f.implantadas = sum(x.situacao == "implantada" for x in lista)
    f.recusadas = sum(x.situacao == "recusada" for x in lista)
    f.aguardando = sum(not x.pago and x.situacao != "recusada" for x in lista)
    f.dias_ate_pagamento = _media_dias([x.primeiro_pagamento_confirmado_em - x.criada_em for x in lista if x.pago])
    f.dias_ate_implantacao = _media_dias([x.implantada_em - x.primeiro_pagamento_confirmado_em for x in lista
                                          if x.implantada_em and x.pago])  # fmt: skip
    f.dias_total = _media_dias([x.implantada_em - x.criada_em for x in lista if x.implantada_em])
    f.etapas = [
        {"rotulo": "Entradas", "valor": f.entradas, "taxa": None},
        {"rotulo": "1º pagamento", "valor": f.pagas, "taxa": _taxa(f.pagas, f.entradas)},
        {"rotulo": "Em implantação", "valor": f.em_implantacao, "taxa": _taxa(f.em_implantacao, f.pagas)},
        {"rotulo": "Implantadas", "valor": f.implantadas, "taxa": _taxa(f.implantadas, f.em_implantacao)},
    ]
    return f


# --------------------------------------------------------- Representantes


@dataclass
class Desempenho:
    nome: str
    representante: m.Representante | None
    enviadas: int = 0
    pagas: int = 0
    implantadas: int = 0
    recusadas: int = 0
    ultimo_envio: datetime | None = None

    @property
    def conversao(self) -> int | None:
        return _taxa(self.implantadas, self.enviadas)


def desempenho(db: Session, inicio: datetime | None) -> list[Desempenho]:
    """Um por representante (e as cadastradas no painel e as contratadas pelo site), do que mais implantou."""
    s = m.SolicitacaoImplantacao
    linhas = {r.id: Desempenho(r.nome, r) for r in db.scalars(sa.select(m.Representante))}
    painel = Desempenho("Cadastradas no painel", None)
    site = Desempenho("Contratação pelo site", None)
    consulta = sa.select(s)
    if inicio:
        consulta = consulta.where(s.criada_em >= inicio)
    for x in db.scalars(consulta):
        d = linhas.get(x.representante_id) if x.representante_id else (painel if x.administrador_id else site)
        d.enviadas += 1
        d.pagas += x.pago
        d.implantadas += x.situacao == "implantada"
        d.recusadas += x.situacao == "recusada"
    # Último envio é de todo o período (para achar quem parou de enviar).
    for rid, ultimo in db.execute(sa.select(s.representante_id, sa.func.max(s.criada_em)).group_by(s.representante_id)):
        if rid in linhas:
            linhas[rid].ultimo_envio = ultimo
    resultado = sorted(linhas.values(), key=lambda d: (-d.implantadas, -d.enviadas, d.nome))
    return resultado + [d for d in (painel, site) if d.enviadas]


def sem_envio(db: Session, dias: int = SEM_ENVIO_DIAS) -> list[tuple[m.Representante, datetime | None]]:
    """Representantes ativos sem nenhum envio há `dias` dias (ou nunca)."""
    s = m.SolicitacaoImplantacao
    ultimo = sa.select(sa.func.max(s.criada_em)).where(s.representante_id == m.Representante.id).scalar_subquery()
    limite = agora() - timedelta(days=dias)
    linhas = db.execute(
        sa.select(m.Representante, ultimo).where(m.Representante.ativo.is_(True))
        .where(sa.or_(ultimo.is_(None), ultimo < limite)).order_by(m.Representante.nome)
    ).all()  # fmt: skip
    return [(r, u) for r, u in linhas]


# ----------------------------------------------------------------- Receita


@dataclass
class Mes:
    rotulo: str
    ativas: int
    receita: Decimal
    novas: int
    canceladas: int


@dataclass
class Receita:
    ativas: int
    receita: Decimal
    ticket: Decimal | None
    meses: list[Mes]
    novas_no_mes: int
    canceladas_no_mes: int


def _meses(hoje: date, quantos: int) -> list[tuple[datetime, datetime]]:
    """(início, fim exclusivo) dos últimos `quantos` meses, do mais antigo ao atual."""
    resultado = []
    for i in range(quantos - 1, -1, -1):
        ano, mes = divmod(hoje.year * 12 + hoje.month - 1 - i, 12)
        inicio = datetime(ano, mes + 1, 1)
        ano2, mes2 = divmod(ano * 12 + mes + 1, 12)
        resultado.append((inicio, datetime(ano2, mes2 + 1, 1)))
    return resultado


def receita(db: Session, meses: int = 12) -> Receita:
    """Receita recorrente pela mensalidade de cada imobiliária. A série mensal
    usa a mensalidade atual de cada uma e as datas de entrada e cancelamento."""
    imobs = list(db.scalars(sa.select(m.Imobiliaria)))
    ativas = [i for i in imobs if i.ativa]
    total = sum((Decimal(i.mensalidade) for i in ativas), Decimal("0"))
    serie = []
    for inicio, fim in _meses(agora().date(), meses):
        no_mes = [i for i in imobs if i.criada_em < fim and (i.desativada_em is None or i.desativada_em >= fim)]
        serie.append(Mes(
            rotulo=f"{MESES[inicio.month - 1]}/{inicio.year % 100:02d}", ativas=len(no_mes),
            receita=sum((Decimal(i.mensalidade) for i in no_mes), Decimal("0")),
            novas=sum(inicio <= i.criada_em < fim for i in imobs),
            canceladas=sum(i.desativada_em is not None and inicio <= i.desativada_em < fim for i in imobs),
        ))  # fmt: skip
    return Receita(
        ativas=len(ativas), receita=total, ticket=(total / len(ativas)).quantize(Decimal("0.01")) if ativas else None,
        meses=serie, novas_no_mes=serie[-1].novas, canceladas_no_mes=serie[-1].canceladas,
    )  # fmt: skip


def validar_plano(mensalidade: str, dia_vencimento: str) -> tuple[Decimal, int]:
    """Mensalidade em reais ("150,00" ou "150.00") e dia do vencimento (1 a 28)."""
    texto = (mensalidade or "").strip().replace("R$", "").replace(" ", "")
    texto = texto.replace(".", "").replace(",", ".") if "," in texto else texto
    try:
        valor = Decimal(texto).quantize(Decimal("0.01"))
    except Exception:
        raise RegraNegocio("Mensalidade inválida (ex.: 150,00).") from None
    if not Decimal("0") <= valor <= Decimal("100000"):
        raise RegraNegocio("Mensalidade inválida (ex.: 150,00).")
    dia = (dia_vencimento or "").strip()
    if not dia.isdigit() or not 1 <= int(dia) <= 28:
        raise RegraNegocio("Dia do vencimento inválido (de 1 a 28).")
    return valor, int(dia)


def definir_plano(db: Session, slug: str, mensalidade: Decimal, dia_vencimento: int) -> None:
    from app.central.services import obter

    r = obter(db, slug)
    r.mensalidade, r.dia_vencimento = mensalidade, dia_vencimento
    db.commit()


# ------------------------------------------------------------------- Leads


def leads(db: Session, situacao: str = "novo") -> list[m.LeadAssociacao]:
    consulta = sa.select(m.LeadAssociacao).order_by(m.LeadAssociacao.criado_em.desc())
    if situacao in SITUACOES_LEAD:
        consulta = consulta.where(m.LeadAssociacao.situacao == situacao)
    return list(db.scalars(consulta))


def contagem_leads(db: Session) -> dict[str, int]:
    linhas = dict(db.execute(sa.select(m.LeadAssociacao.situacao, sa.func.count()).group_by(m.LeadAssociacao.situacao)).all())
    return {s: linhas.get(s, 0) for s in SITUACOES_LEAD} | {"todos": sum(linhas.values())}


def lead(db: Session, id_: str) -> m.LeadAssociacao:
    x = db.get(m.LeadAssociacao, id_)
    if x is None:
        raise NaoEncontrado("Lead não encontrado.")
    return x


def atualizar_lead(db: Session, id_: str, situacao: str, anotacao: str) -> None:
    x = lead(db, id_)
    if situacao not in SITUACOES_LEAD or (situacao == "convertido" and not x.solicitacao_id):
        raise RegraNegocio("Situação inválida (para converter, use “Criar solicitação”).")
    x.situacao, x.anotacao, x.atualizado_em = situacao, (anotacao or "").strip()[:2000], agora()
    db.commit()


def converter(db: Session, id_: str, solicitacao_id: str) -> None:
    x = lead(db, id_)
    x.situacao, x.solicitacao_id, x.atualizado_em = "convertido", solicitacao_id, agora()
    db.commit()


def dados_para_solicitacao(x: m.LeadAssociacao):
    """O que o pré-cadastro já traz para o formulário da solicitação."""
    from app.central.representantes import UFS, DadosCorretor

    cidade, uf = x.cidade, ""
    partes = [p.strip() for p in x.cidade.replace("-", "/").split("/") if p.strip()]
    if len(partes) >= 2 and partes[-1].upper() in UFS:
        cidade, uf = "/".join(partes[:-1]), partes[-1].upper()
    return DadosCorretor(nome=x.nome, email=x.email, telefone=x.whatsapp, creci=x.creci, cidade=cidade, uf=uf,
                         observacoes=f"Pré-cadastro do site ({x.perfil}).")  # fmt: skip

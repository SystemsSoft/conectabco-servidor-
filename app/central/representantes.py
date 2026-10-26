"""Representantes da associação e as solicitações de implantação que eles
enviam (o corretor e a imobiliária a implantar)."""

import re
import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.central import models as m
from app.core.documentos import validar_cpf_cnpj
from app.core.errors import NaoEncontrado, RegraNegocio
from app.core.seguranca import hash_senha
from app.core.tempo import agora

SITUACOES = {
    "nova": "Nova",
    "em_andamento": "Em implantação",
    "implantada": "Implantada",
    "recusada": "Recusada",
}
UFS = ("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO").split()
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DOMINIO = re.compile(r"^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$")


def _texto(valor: str, rotulo: str, maximo: int, obrigatorio: bool = True) -> str:
    valor = (valor or "").strip()
    if obrigatorio and not valor:
        raise RegraNegocio(f"Informe {rotulo}.")
    if len(valor) > maximo:
        raise RegraNegocio(f"{rotulo[0].upper()}{rotulo[1:]}: no máximo {maximo} caracteres.")
    return valor


def _email(valor: str, obrigatorio: bool = True) -> str:
    valor = _texto(valor, "o e-mail", 200, obrigatorio).lower()
    if valor and not _EMAIL.match(valor):
        raise RegraNegocio("E-mail inválido.")
    return valor


def _telefone(valor: str, obrigatorio: bool = True) -> str:
    valor = _texto(valor, "o telefone", 30, obrigatorio)
    if valor and len(re.sub(r"\D", "", valor)) < 10:
        raise RegraNegocio("Telefone inválido: informe o DDD e o número.")
    return valor


def _numero(valor: str, rotulo: str) -> int | None:
    valor = (valor or "").strip().replace(".", "")
    if not valor:
        return None
    if not valor.isdigit() or int(valor) > 1_000_000:
        raise RegraNegocio(f"Quantidade de {rotulo} inválida.")
    return int(valor)


# --------------------------------------------------------- Representantes


def representante(db: Session, id_: str) -> m.Representante:
    r = db.get(m.Representante, id_)
    if r is None:
        raise NaoEncontrado("Representante não encontrado.")
    return r


def salvar_representante(
    db: Session, id_: str | None, nome: str, login: str, email: str, telefone: str,
    regiao: str, senha: str = "", ativo: bool = True,
) -> m.Representante:  # fmt: skip
    """Cria (sem id) ou altera o representante. Senha nova derruba as sessões."""
    from app.modules.equipe.services import _validar_login, _validar_senha, aparar

    # Tudo conferido antes de mexer no registro (nada pela metade na sessão).
    nome = _texto(nome, "o nome", 150)
    login, senha = aparar(login), aparar(senha)
    _validar_login(login)
    email, telefone = _email(email), _telefone(telefone)
    regiao = _texto(regiao, "a região", 150, obrigatorio=False)
    if senha or id_ is None:
        _validar_senha(senha)
    outro = db.scalar(sa.select(m.Representante).where(sa.func.lower(m.Representante.login) == login.lower()))
    if outro is not None and outro.id != id_:
        raise RegraNegocio(f"Já existe um representante com o usuário '{login}'.")
    if id_ is None:
        r = m.Representante(id=str(uuid.uuid4()), versao=1, tentativas=0, criado_em=agora())
        db.add(r)
    else:
        r = representante(db, id_)
        if not ativo and r.ativo or senha:
            r.versao += 1  # derruba as sessões abertas
    r.nome, r.login, r.email, r.telefone, r.regiao, r.ativo = nome, login, email, telefone, regiao, ativo
    if senha:
        r.senha_hash, r.tentativas, r.bloqueado_ate = hash_senha(senha), 0, None
    db.commit()
    return r


def representantes(db: Session) -> list[tuple[m.Representante, int, int]]:
    """Cada representante com o total de solicitações e as implantadas."""
    total = sa.func.count(m.SolicitacaoImplantacao.id)
    implantadas = sa.func.count(sa.case((m.SolicitacaoImplantacao.situacao == "implantada", 1)))
    linhas = db.execute(
        sa.select(m.Representante, total, implantadas)
        .outerjoin(m.SolicitacaoImplantacao, m.SolicitacaoImplantacao.representante_id == m.Representante.id)
        .group_by(m.Representante.id).order_by(m.Representante.nome)
    ).all()  # fmt: skip
    return [(r, t, i) for r, t, i in linhas]


# ------------------------------------------------------------ Solicitações


@dataclass
class DadosCorretor:
    nome: str = ""
    cpf_cnpj: str = ""
    creci: str = ""
    email: str = ""
    telefone: str = ""
    nome_imobiliaria: str = ""
    cidade: str = ""
    uf: str = ""
    dominio: str = ""
    imoveis: str = ""
    contratos: str = ""
    usuarios: str = ""
    observacoes: str = ""


def enviar_solicitacao(db: Session, rep: m.Representante, d: DadosCorretor) -> m.SolicitacaoImplantacao:
    """Confere os dados do corretor e registra a solicitação como nova."""
    cpf_cnpj = re.sub(r"\D", "", d.cpf_cnpj or "")
    if not validar_cpf_cnpj(cpf_cnpj):
        raise RegraNegocio("CPF ou CNPJ inválido.")
    uf = (d.uf or "").strip().upper()
    if uf not in UFS:
        raise RegraNegocio("Escolha o estado (UF).")
    dominio = (d.dominio or "").strip().lower().removeprefix("https://").removeprefix("http://").strip("/")
    if dominio and not _DOMINIO.match(dominio):
        raise RegraNegocio("Domínio inválido (ex.: joaoimoveis.com.br).")
    momento = agora()
    s = m.SolicitacaoImplantacao(
        id=str(uuid.uuid4()), representante_id=rep.id, situacao="nova",
        nome=_texto(d.nome, "o nome do corretor", 150), cpf_cnpj=cpf_cnpj,
        creci=_texto(d.creci, "o CRECI", 30), email=_email(d.email), telefone=_telefone(d.telefone),
        nome_imobiliaria=_texto(d.nome_imobiliaria, "o nome da imobiliária", 200),
        cidade=_texto(d.cidade, "a cidade", 120), uf=uf, dominio=dominio,
        imoveis=_numero(d.imoveis, "imóveis"), contratos=_numero(d.contratos, "contratos"),
        usuarios=_numero(d.usuarios, "usuários"),
        observacoes=_texto(d.observacoes, "as observações", 2000, obrigatorio=False),
        resposta="", criada_em=momento, atualizada_em=momento,
    )  # fmt: skip
    db.add(s)
    db.commit()
    return s


def solicitacao(db: Session, id_: str) -> m.SolicitacaoImplantacao:
    s = db.get(m.SolicitacaoImplantacao, id_)
    if s is None:
        raise NaoEncontrado("Solicitação não encontrada.")
    return s


def solicitacoes(db: Session, situacao: str = "", representante_id: str = "") -> list[m.SolicitacaoImplantacao]:
    consulta = sa.select(m.SolicitacaoImplantacao).order_by(m.SolicitacaoImplantacao.criada_em.desc())
    if situacao:
        consulta = consulta.where(m.SolicitacaoImplantacao.situacao == situacao)
    if representante_id:
        consulta = consulta.where(m.SolicitacaoImplantacao.representante_id == representante_id)
    return list(db.scalars(consulta))


def contagem(db: Session) -> dict[str, int]:
    linhas = db.execute(
        sa.select(m.SolicitacaoImplantacao.situacao, sa.func.count()).group_by(m.SolicitacaoImplantacao.situacao)
    ).all()  # fmt: skip
    return {s: 0 for s in SITUACOES} | dict(linhas)


def atualizar(db: Session, id_: str, situacao: str, resposta: str, imobiliaria_slug: str | None = None) -> None:
    """Muda a situação e a resposta que o representante vê."""
    if situacao not in SITUACOES:
        raise RegraNegocio("Situação inválida.")
    s = solicitacao(db, id_)
    s.situacao = situacao
    s.resposta = _texto(resposta, "a resposta", 2000, obrigatorio=False)
    if imobiliaria_slug is not None:
        s.imobiliaria_slug = imobiliaria_slug
    s.atualizada_em = agora()
    db.commit()


def sugestao_de_slug(nome: str) -> str:
    """Identificador sugerido a partir do nome da imobiliária."""
    import unicodedata

    texto = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().lower()
    texto = re.sub(r"\b(imoveis|imobiliaria|ltda|me|eireli|negocios|corretora)\b", " ", texto)
    return re.sub(r"[^a-z0-9]+", "-", texto).strip("-")[:40].strip("-")

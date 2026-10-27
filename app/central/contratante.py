"""Dados do CONTRATANTE do contrato de prestação de serviços da associação
(quadro da primeira página): quem contrata, endereços, contatos, internet e
a implantação. Um registro por imobiliária, no banco central."""

import re
from dataclasses import dataclass, fields
from datetime import date

from sqlalchemy.orm import Session

from app.central import models as m
from app.central.representantes import UFS
from app.core.documentos import validar_cnpj, validar_cpf
from app.core.errors import RegraNegocio
from app.core.tempo import agora

_HORARIO = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@dataclass
class DadosContrato:
    """Como vêm do formulário (texto); `validar` confere e converte."""

    nome: str = ""
    endereco: str = ""
    numero: str = ""
    bairro: str = ""
    cidade: str = ""
    uf: str = ""
    cpf: str = ""
    identidade: str = ""
    cnpj: str = ""
    creci_pj: str = ""
    creci: str = ""
    nome_comercial: str = ""
    endereco_comercial: str = ""
    telefone_1: str = ""
    telefone_2: str = ""
    servidor: str = ""
    dns: str = ""
    instagram: str = ""
    facebook: str = ""
    tiktok: str = ""
    youtube: str = ""
    data_implantacao: str = ""
    horario_implantacao: str = ""
    data_assinatura: str = ""

    @classmethod
    def do_formulario(cls, formulario) -> "DadosContrato":
        return cls(**{f.name: str(formulario.get(f"contrato_{f.name}", "")).strip() for f in fields(cls)})

    @classmethod
    def do_registro(cls, r: m.DadosContratante | None) -> "DadosContrato":
        if r is None:
            return cls()
        valores = {}
        for f in fields(cls):
            v = getattr(r, f.name)
            valores[f.name] = v.isoformat() if isinstance(v, date) else (v or "")
        return cls(**valores)


# Obrigatórios no contrato (um de CPF/CNPJ e um de CRECI/CRECI PJ, conferidos à parte).
OBRIGATORIOS = {"nome": "o nome", "endereco": "o endereço", "numero": "o número", "bairro": "o bairro",
                "cidade": "a cidade", "telefone_1": "o telefone comercial"}  # fmt: skip
_MAXIMOS = {c.name: c.type.length for c in m.DadosContratante.__table__.columns if getattr(c.type, "length", None)}


def _data(texto: str, rotulo: str) -> date | None:
    if not texto:
        return None
    try:
        return date.fromisoformat(texto)
    except ValueError:
        raise RegraNegocio(f"{rotulo} inválida.") from None


def validar(d: DadosContrato) -> dict:
    """Confere os dados do contratante e devolve os valores a gravar."""
    valores = {f.name: getattr(d, f.name).strip() for f in fields(DadosContrato)}
    for campo, rotulo in OBRIGATORIOS.items():
        if not valores[campo]:
            raise RegraNegocio(f"Contrato: informe {rotulo} do contratante.")
    for campo, valor in valores.items():
        if campo in _MAXIMOS and campo not in ("cpf", "cnpj") and len(valor) > _MAXIMOS[campo]:
            raise RegraNegocio(f"Contrato: {campo.replace('_', ' ')} com mais de {_MAXIMOS[campo]} caracteres.")
    valores["uf"] = valores["uf"].upper()
    if valores["uf"] not in UFS:
        raise RegraNegocio("Contrato: escolha o estado (UF) do contratante.")
    valores["cpf"] = re.sub(r"\D", "", valores["cpf"])
    valores["cnpj"] = re.sub(r"\D", "", valores["cnpj"])
    if not (valores["cpf"] or valores["cnpj"]):
        raise RegraNegocio("Contrato: informe o CPF ou o CNPJ do contratante.")
    if valores["cpf"] and not validar_cpf(valores["cpf"]):
        raise RegraNegocio("Contrato: CPF inválido.")
    if valores["cnpj"] and not validar_cnpj(valores["cnpj"]):
        raise RegraNegocio("Contrato: CNPJ inválido.")
    if valores["cpf"] and not valores["identidade"]:
        raise RegraNegocio("Contrato: informe a identidade (RG) do contratante.")
    if not (valores["creci"] or valores["creci_pj"]):
        raise RegraNegocio("Contrato: informe o CRECI ou o CRECI PJ.")
    for campo in ("telefone_1", "telefone_2"):
        if valores[campo] and len(re.sub(r"\D", "", valores[campo])) < 10:
            raise RegraNegocio("Contrato: telefone inválido (informe o DDD e o número).")
    valores["data_implantacao"] = _data(valores["data_implantacao"], "Data da implantação")
    valores["data_assinatura"] = _data(valores["data_assinatura"], "Data da assinatura")
    if valores["horario_implantacao"] and not _HORARIO.match(valores["horario_implantacao"]):
        raise RegraNegocio("Contrato: horário da implantação inválido (use HH:MM).")
    return valores


def obter(db: Session, slug: str) -> m.DadosContratante | None:
    return db.get(m.DadosContratante, slug)


def salvar(db: Session, slug: str, valores: dict) -> m.DadosContratante:
    """Grava os valores já conferidos por `validar`."""
    r = db.get(m.DadosContratante, slug) or m.DadosContratante(imobiliaria_slug=slug)
    for campo, valor in valores.items():
        setattr(r, campo, valor)
    r.atualizado_em = agora()
    db.add(r)
    db.commit()
    return r


def da_solicitacao(s: m.SolicitacaoImplantacao) -> DadosContrato:
    """O que já se sabe pela solicitação do representante."""
    documento = re.sub(r"\D", "", s.cpf_cnpj)
    return DadosContrato(
        nome=s.nome, cidade=s.cidade, uf=s.uf, telefone_1=s.telefone, nome_comercial=s.nome_imobiliaria,
        cpf=documento if len(documento) == 11 else "", cnpj=documento if len(documento) == 14 else "",
        creci=s.creci if len(documento) == 11 else "", creci_pj=s.creci if len(documento) == 14 else "",
    )  # fmt: skip

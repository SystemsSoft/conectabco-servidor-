"""Contratação do sistema pelo site: o interessado preenche os dados do
contratante, vê o contrato da associação preenchido e assina — de forma
eletrônica, aqui, ou com a conta gov.br (baixa o PDF, assina no Assinador do
ITI e envia de volta). Assinado, vira solicitação de implantação (Financeiro e
Tecnologia) e lead convertido no Comercial, com o contrato anexado."""

import io
import re
import secrets
import unicodedata
import uuid
from dataclasses import fields
from datetime import timedelta
from typing import BinaryIO

from sqlalchemy.orm import Session

from app.central import contrato_pdf
from app.central import contratante as ct
from app.central import financeiro as fin
from app.central import models as m
from app.central import representantes as rep
from app.core.errors import NaoEncontrado, RegraNegocio
from app.core.tempo import agora

# Os campos do contratante que o próprio interessado preenche (os de
# implantação — servidor, DNS, data e horário — ficam com a associação).
CAMPOS = ("nome", "nome_comercial", "cpf", "identidade", "cnpj", "creci", "creci_pj", "endereco", "numero",
          "bairro", "cidade", "uf", "endereco_comercial", "telefone_1", "telefone_2", "instagram", "facebook",
          "tiktok", "youtube")  # fmt: skip
VALIDADE = timedelta(days=30)  # link de um contrato ainda não assinado
LIMITE_PDF = 10 * 1024 * 1024
ASSINADOR_GOVBR = "https://assinador.iti.br"
VALIDADOR_ITI = "https://validar.iti.gov.br"
METODOS = {"eletronica": "Assinatura eletrônica no site", "govbr": "Assinatura gov.br"}
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_DOMINIO = re.compile(r"^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$")


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return " ".join(sem_acento.lower().split())


def iniciar(db: Session, formulario: dict[str, str]) -> m.ContratoDigital:
    """Confere os dados do contratante e abre o contrato para assinatura."""
    if formulario.get("lgpd") != "on":
        raise RegraNegocio("Aceite o uso dos seus dados para a contratação (LGPD).")
    dados = ct.DadosContrato(**{c: (formulario.get(c) or "").strip() for c in CAMPOS})
    valores = ct.validar(dados)
    email = (formulario.get("email") or "").strip().lower()
    if not _EMAIL.match(email) or len(email) > 200:
        raise RegraNegocio("E-mail inválido.")
    site = (formulario.get("site") or "").strip().lower().removeprefix("https://").removeprefix("http://").strip("/")
    if site and not _DOMINIO.match(site):
        raise RegraNegocio("Endereço do site inválido (ex.: joaoimoveis.com.br).")
    guardados = {c: valores[c] for c in CAMPOS} | {"site": site}
    momento = agora()
    c = m.ContratoDigital(
        id=str(uuid.uuid4()), token=secrets.token_urlsafe(32), dados=guardados, email=email,
        situacao="aguardando", metodo="", assinatura_nome="", ip="", navegador="", hash_contrato="",
        chave_assinado="", criado_em=momento, atualizado_em=momento,
    )  # fmt: skip
    db.add(c)
    db.commit()
    return c


def por_token(db: Session, token: str) -> m.ContratoDigital:
    from sqlalchemy import select

    c = db.scalar(select(m.ContratoDigital).where(m.ContratoDigital.token == token)) if token else None
    if c is None or (c.situacao == "aguardando" and agora() - c.criado_em > VALIDADE):
        raise NaoEncontrado("Link de contratação inválido ou expirado.")
    return c


def pdf(c: m.ContratoDigital) -> bytes:
    """O contrato preenchido (para ler e para assinar no gov.br)."""
    return contrato_pdf.gerar(c.dados, agora().date())


def assinar_eletronicamente(db: Session, c: m.ContratoDigital, nome_digitado: str, aceite: str,
                            ip: str, navegador: str) -> m.SolicitacaoImplantacao:  # fmt: skip
    """Aceite com o nome completo digitado; o contrato ganha a página de registro."""
    _ainda_aguardando(c)
    if aceite != "on":
        raise RegraNegocio("Marque que leu e concorda com o contrato.")
    if _normalizar(nome_digitado) != _normalizar(c.dados["nome"]):
        raise RegraNegocio("Digite o seu nome completo exatamente como no contrato.")
    contrato = pdf(c)
    momento = agora()
    c.hash_contrato = contrato_pdf.sha256(contrato)
    documento = contrato_pdf._formatar_documento(c.dados.get("cpf") or c.dados.get("cnpj") or "")
    assinado = contrato_pdf.com_registro_de_assinatura(contrato, {
        "Contratante": c.dados["nome"], "CPF/CNPJ": documento, "E-mail": c.email,
        "Nome digitado": nome_digitado.strip(), "Assinado em": momento.strftime("%d/%m/%Y %H:%M:%S (Brasília)"),
        "IP": ip or "—", "Navegador": (navegador or "—")[:300], "SHA-256 do contrato": c.hash_contrato,
    })  # fmt: skip
    c.metodo, c.assinatura_nome = "eletronica", nome_digitado.strip()[:150]
    return _finalizar(db, c, assinado, "contrato-assinado.pdf", ip, navegador)


def receber_govbr(db: Session, c: m.ContratoDigital, arquivo: BinaryIO, ip: str,
                  navegador: str) -> m.SolicitacaoImplantacao:  # fmt: skip
    """O PDF assinado no Assinador gov.br: confere que é PDF e que tem assinatura
    digital (a validade da assinatura se confere em validar.iti.gov.br)."""
    _ainda_aguardando(c)
    conteudo = arquivo.read(LIMITE_PDF + 1)
    if len(conteudo) > LIMITE_PDF:
        raise RegraNegocio("Arquivo grande demais (máximo 10 MB).")
    if not conteudo.startswith(b"%PDF"):
        raise RegraNegocio("Envie o contrato em PDF.")
    if b"/ByteRange" not in conteudo or b"/Sig" not in conteudo:
        raise RegraNegocio("Este PDF não tem assinatura digital. Assine no Assinador gov.br antes de enviar.")
    c.hash_contrato = contrato_pdf.sha256(conteudo)
    c.metodo = "govbr"
    return _finalizar(db, c, conteudo, "contrato-assinado-govbr.pdf", ip, navegador)


def _ainda_aguardando(c: m.ContratoDigital) -> None:
    if c.situacao != "aguardando":
        raise RegraNegocio("Este contrato já foi assinado.")


def _finalizar(db: Session, c: m.ContratoDigital, conteudo: bytes, nome_arquivo: str, ip: str,
               navegador: str) -> m.SolicitacaoImplantacao:  # fmt: skip
    """Assinado: solicitação de implantação com o contrato anexado e lead convertido."""
    d = c.dados
    documento = d.get("cpf") or d.get("cnpj") or ""
    s = rep.enviar_solicitacao(db, None, rep.DadosCorretor(
        nome=d["nome"], cpf_cnpj=documento, creci=d.get("creci") or d.get("creci_pj") or "", email=c.email,
        telefone=d["telefone_1"], nome_imobiliaria=d.get("nome_comercial") or d["nome"], cidade=d["cidade"],
        uf=d["uf"], dominio=d.get("site", ""),
        observacoes=f"Contratou pelo site: contrato assinado ({METODOS[c.metodo].lower()}).",
    ))  # fmt: skip
    doc = fin.enviar_documento(db, s, None, io.BytesIO(conteudo), nome_arquivo, "contrato",
                               METODOS[c.metodo])  # fmt: skip
    momento = agora()
    c.situacao, c.assinado_em, c.atualizado_em = "assinado", momento, momento
    c.ip, c.navegador = (ip or "")[:64], (navegador or "")[:300]
    c.chave_assinado, c.solicitacao_id = doc.chave, s.id
    db.add(m.LeadAssociacao(
        id=str(uuid.uuid4()), nome=d["nome"], email=c.email, whatsapp=d["telefone_1"],
        creci=d.get("creci") or d.get("creci_pj") or "", cidade=f"{d['cidade']}/{d['uf']}",
        perfil="Contratação online", quer_sistema=True, situacao="convertido",
        anotacao=f"Contrato assinado pelo site ({METODOS[c.metodo].lower()}).", solicitacao_id=s.id,
        criado_em=momento, atualizado_em=momento,
    ))  # fmt: skip
    db.commit()
    return s


def da_solicitacao(db: Session, solicitacao_id: str) -> m.ContratoDigital | None:
    from sqlalchemy import select

    return db.scalar(select(m.ContratoDigital).where(m.ContratoDigital.solicitacao_id == solicitacao_id))


def dados_para_contratante(c: m.ContratoDigital) -> ct.DadosContrato:
    """O contratante do contrato assinado, para o cadastro da imobiliária."""
    return ct.DadosContrato(**{f.name: c.dados.get(f.name, "") for f in fields(ct.DadosContrato) if f.name in c.dados})

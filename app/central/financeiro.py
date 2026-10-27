"""Financeiro das solicitações de implantação: documentos (boletos de
cobrança, comprovantes de pagamento) e a confirmação do 1º pagamento, que
libera a Tecnologia para implantar."""

import uuid
from datetime import date
from pathlib import Path
from typing import BinaryIO

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.central import models as m
from app.core.armazenamento import armazenamento, temporario
from app.core.errors import NaoEncontrado, RegraNegocio
from app.core.tempo import agora
from app.core.ulid import novo_ulid

TIPOS = {"boleto": "Boleto de cobrança", "comprovante": "Comprovante de pagamento",
         "contrato": "Contrato assinado", "logo": "Logotipo", "outro": "Outro"}
FILTROS = {"aguardando": "Aguardando 1º pagamento", "pago": "1º pagamento confirmado", "todas": "Todas"}
MB = 1024 * 1024
LIMITE = 10 * MB
_FORMATOS = {
    "pdf": ("application/pdf", (b"%PDF",)),
    "jpg": ("image/jpeg", (b"\xff\xd8\xff",)),
    "jpeg": ("image/jpeg", (b"\xff\xd8\xff",)),
    "png": ("image/png", (b"\x89PNG\r\n\x1a\n",)),
}
_PREFIXO = "plataforma/solicitacoes"


def solicitacoes(db: Session, filtro: str = "aguardando") -> list[m.SolicitacaoImplantacao]:
    """As que o financeiro acompanha (as recusadas ficam só em "todas")."""
    s = m.SolicitacaoImplantacao
    consulta = sa.select(s).order_by(s.criada_em.desc())
    if filtro == "aguardando":
        consulta = consulta.where(s.primeiro_pagamento_confirmado_em.is_(None), s.situacao != "recusada")
    elif filtro == "pago":
        consulta = consulta.where(s.primeiro_pagamento_confirmado_em.is_not(None))
    return list(db.scalars(consulta))


def contagem(db: Session) -> dict[str, int]:
    s = m.SolicitacaoImplantacao
    aguardando = db.scalar(sa.select(sa.func.count()).where(
        s.primeiro_pagamento_confirmado_em.is_(None), s.situacao != "recusada"))  # fmt: skip
    pago = db.scalar(sa.select(sa.func.count()).where(s.primeiro_pagamento_confirmado_em.is_not(None)))
    return {"aguardando": aguardando, "pago": pago, "todas": db.scalar(sa.select(sa.func.count(s.id)))}


# ---------------------------------------------------------- 1º pagamento


def confirmar_pagamento(db: Session, s: m.SolicitacaoImplantacao, admin: m.Administrador,
                        data_pagamento: str, observacao: str) -> None:  # fmt: skip
    if s.situacao == "recusada":
        raise RegraNegocio("Solicitação recusada: não há pagamento a confirmar.")
    try:
        quando = date.fromisoformat(data_pagamento) if data_pagamento else None
    except ValueError:
        raise RegraNegocio("Data do pagamento inválida.") from None
    if quando is None:
        raise RegraNegocio("Informe a data do 1º pagamento.")
    if quando > agora().date():
        raise RegraNegocio("A data do pagamento não pode ser futura.")
    s.primeiro_pagamento_em, s.primeiro_pagamento_confirmado_em = quando, agora()
    s.primeiro_pagamento_por_id = admin.id
    s.observacao_financeira = (observacao or "").strip()[:2000]
    s.atualizada_em = agora()
    db.commit()


def desfazer_pagamento(db: Session, s: m.SolicitacaoImplantacao) -> None:
    """Só enquanto a Tecnologia não avançou (situação ainda nova)."""
    if s.situacao != "nova":
        raise RegraNegocio("A Tecnologia já avançou esta solicitação: o pagamento não pode ser desfeito.")
    s.primeiro_pagamento_em = s.primeiro_pagamento_confirmado_em = s.primeiro_pagamento_por_id = None
    s.atualizada_em = agora()
    db.commit()


def exigir_pagamento(s: m.SolicitacaoImplantacao) -> None:
    """Trava da Tecnologia: em implantação e implantada só depois do financeiro."""
    if not s.pago:
        raise RegraNegocio("O financeiro ainda não confirmou o 1º pagamento desta imobiliária.")


# ------------------------------------------------------------ Documentos


def documento(db: Session, id_: str) -> m.DocumentoSolicitacao:
    d = db.get(m.DocumentoSolicitacao, id_)
    if d is None:
        raise NaoEncontrado("Documento não encontrado.")
    return d


def documentos(db: Session, s: m.SolicitacaoImplantacao) -> list[m.DocumentoSolicitacao]:
    return list(db.scalars(
        sa.select(m.DocumentoSolicitacao).where(m.DocumentoSolicitacao.solicitacao_id == s.id)
        .order_by(m.DocumentoSolicitacao.criado_em.desc())
    ))  # fmt: skip


def enviar_documento(db: Session, s: m.SolicitacaoImplantacao, admin: m.Administrador | None, conteudo: BinaryIO,
                     nome: str, tipo: str, descricao: str) -> m.DocumentoSolicitacao:  # fmt: skip
    """PDF, JPG ou PNG de até 10 MB, conferido pelo início do arquivo."""
    if tipo not in TIPOS:
        raise RegraNegocio("Escolha o tipo do documento.")
    nome = Path(nome or "").name.strip()[:255]
    extensao = nome.rsplit(".", 1)[-1].lower() if "." in nome else ""
    if extensao not in _FORMATOS:
        raise RegraNegocio("Formato não aceito. Envie PDF, JPG ou PNG.")
    tipo_mime, assinaturas = _FORMATOS[extensao]
    provisorio, tamanho = temporario(), 0
    try:
        with provisorio.open("wb") as saida:
            while parte := conteudo.read(MB):
                if tamanho == 0 and not parte.startswith(assinaturas):
                    raise RegraNegocio(f"O arquivo não é um {extensao.upper()} válido.")
                tamanho += len(parte)
                if tamanho > LIMITE:
                    raise RegraNegocio("Arquivo grande demais (máximo 10 MB).")
                saida.write(parte)
        if tamanho == 0:
            raise RegraNegocio("O arquivo está vazio.")
        d = m.DocumentoSolicitacao(
            id=str(uuid.uuid4()), solicitacao_id=s.id, tipo=tipo, nome=nome,
            descricao=(descricao or "").strip()[:300], tipo_mime=tipo_mime, tamanho=tamanho,
            chave=f"{_PREFIXO}/{s.id}/{novo_ulid()}", enviado_por_id=admin.id if admin else None, criado_em=agora(),
        )  # fmt: skip
        armazenamento().gravar(d.chave, provisorio, tipo_mime,
                               {"origem": "plataforma", "solicitacao": s.id, "documento": d.id, "tipo": tipo})  # fmt: skip
    finally:
        provisorio.unlink(missing_ok=True)
    db.add(d)
    try:
        db.commit()
    except Exception:
        db.rollback()
        armazenamento().apagar(d.chave)
        raise
    return d


def logo(db: Session, s: m.SolicitacaoImplantacao) -> m.DocumentoSolicitacao | None:
    """O logotipo mais recente guardado na solicitação (ex.: enviado na contratação)."""
    return next((d for d in documentos(db, s) if d.tipo == "logo"), None)


def conteudo(d: m.DocumentoSolicitacao) -> bytes:
    loja, chave = onde(d)
    with loja.local(chave) as caminho:
        return caminho.read_bytes()


def remover_documento(db: Session, d: m.DocumentoSolicitacao) -> None:
    armazenamento().apagar(d.chave)
    db.delete(d)
    db.commit()


def onde(d: m.DocumentoSolicitacao):
    """Armazenamento e chave, só dentro do prefixo da plataforma."""
    if not d.chave.startswith(f"{_PREFIXO}/{d.solicitacao_id}/"):
        raise NaoEncontrado("Documento não encontrado.")
    return armazenamento(), d.chave

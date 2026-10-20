"""Gerenciador de documentos do Financeiro: pastas com PDF, Word e Excel
enviados do computador (boletos baixados do banco, relatórios e outros)."""

from pathlib import Path
from typing import BinaryIO

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.errors import NaoEncontrado, RegraNegocio, validar_id
from app.modules.arquivos import services as arquivos
from app.modules.arquivos.models import Arquivo
from app.modules.financeiro import models as m
from app.modules.financeiro import schemas as s

EXTENSOES = ("pdf", "doc", "docx", "xls", "xlsx")


def _extensao_aceita(nome: str) -> None:
    ext = nome.rsplit(".", 1)[-1].lower() if "." in nome else ""
    if ext not in EXTENSOES:
        raise RegraNegocio(
            f'"{nome}" não é aceito. Envie PDF, Word ou Excel '
            f"({', '.join(EXTENSOES).upper()})."
        )


def _titulo(nome_arquivo: str) -> str:
    """Título inicial: o nome do arquivo sem a extensão."""
    return Path(nome_arquivo).stem.strip()[:255] or "Documento"


class DocumentoService:
    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------- Pastas

    def listar_pastas(self) -> list[s.PastaSaida]:
        contagem = (
            sa.select(sa.func.count(m.DocumentoFinanceiro.id))
            .where(m.DocumentoFinanceiro.pasta_id == m.PastaDocumento.id)
            .scalar_subquery()
        )
        linhas = self.db.execute(
            sa.select(m.PastaDocumento, contagem).order_by(m.PastaDocumento.nome)
        ).all()
        return [
            s.PastaSaida.model_validate(p).model_copy(update={"documentos": n})
            for p, n in linhas
        ]

    def salvar_pasta(self, id: str, dados: s.PastaEntrada) -> tuple[s.PastaSaida, bool]:
        id = validar_id(id)
        nome = dados.nome.strip()
        if not nome:
            raise RegraNegocio("Informe o nome da pasta.")
        repetida = self.db.scalar(
            sa.select(m.PastaDocumento.id).where(
                sa.func.lower(m.PastaDocumento.nome) == nome.lower(),
                m.PastaDocumento.id != id,
            )
        )
        if repetida:
            raise RegraNegocio(f'Já existe uma pasta chamada "{nome}".')
        pasta = self.db.get(m.PastaDocumento, id)
        criado = pasta is None
        if criado:
            pasta = m.PastaDocumento(id=id)
            self.db.add(pasta)
        pasta.nome = nome
        self.db.commit()
        return self._pasta_saida(pasta), criado

    def remover_pasta(self, id: str) -> None:
        pasta = self._pasta(id)
        for d in self.db.scalars(
            sa.select(m.DocumentoFinanceiro).where(m.DocumentoFinanceiro.pasta_id == id)
        ):
            self._apagar_arquivo(d.arquivo_id)
            self.db.delete(d)
        self.db.delete(pasta)
        self.db.commit()

    # --------------------------------------------------------- Documentos

    def listar(self, pasta_id: str) -> list[s.DocumentoSaida]:
        self._pasta(pasta_id)
        q = (
            sa.select(m.DocumentoFinanceiro, Arquivo)
            .join(Arquivo, Arquivo.id == m.DocumentoFinanceiro.arquivo_id)
            .where(m.DocumentoFinanceiro.pasta_id == pasta_id)
            .order_by(m.DocumentoFinanceiro.nome)
        )
        return [self._saida(d, a) for d, a in self.db.execute(q).all()]

    def enviar(
        self, pasta_id: str, conteudo: BinaryIO, nome_arquivo: str, usuario_id: str
    ) -> s.DocumentoSaida:
        self._pasta(pasta_id)
        nome_arquivo = Path(nome_arquivo or "").name
        _extensao_aceita(nome_arquivo)
        a = arquivos.salvar(self.db, conteudo, nome_arquivo, "arquivo", usuario_id)
        d = m.DocumentoFinanceiro(pasta_id=pasta_id, nome=_titulo(a.nome), arquivo_id=a.id)
        self.db.add(d)
        self.db.commit()
        return self._saida(d, a)

    def salvar(self, id: str, dados: s.DocumentoEntrada) -> s.DocumentoSaida:
        d = self._documento(id)
        nome = dados.nome.strip()
        if not nome:
            raise RegraNegocio("Informe o nome do documento.")
        self._pasta(dados.pasta_id)
        d.nome = nome
        d.pasta_id = dados.pasta_id
        self.db.commit()
        return self._saida(d, self.db.get(Arquivo, d.arquivo_id))

    def substituir(
        self, id: str, conteudo: BinaryIO, nome_arquivo: str, usuario_id: str
    ) -> s.DocumentoSaida:
        """Troca o arquivo e mantém o nome, a pasta e o histórico."""
        d = self._documento(id)
        nome_arquivo = Path(nome_arquivo or "").name
        _extensao_aceita(nome_arquivo)
        a = arquivos.salvar(self.db, conteudo, nome_arquivo, "arquivo", usuario_id)
        antigo, d.arquivo_id = d.arquivo_id, a.id
        self.db.flush()
        self._apagar_arquivo(antigo)
        self.db.commit()
        return self._saida(d, a)

    def remover(self, id: str) -> None:
        d = self._documento(id)
        self._apagar_arquivo(d.arquivo_id)
        self.db.delete(d)
        self.db.commit()

    # ------------------------------------------------------------- Apoio

    def _pasta(self, id: str) -> m.PastaDocumento:
        pasta = self.db.get(m.PastaDocumento, validar_id(id))
        if pasta is None:
            raise NaoEncontrado("Pasta não encontrada.")
        return pasta

    def _documento(self, id: str) -> m.DocumentoFinanceiro:
        d = self.db.get(m.DocumentoFinanceiro, validar_id(id))
        if d is None:
            raise NaoEncontrado("Documento não encontrado.")
        return d

    def _apagar_arquivo(self, arquivo_id: str) -> None:
        if a := self.db.get(Arquivo, arquivo_id):
            self.db.delete(a)
        arquivos.remover_arquivo(arquivo_id)

    def _pasta_saida(self, p: m.PastaDocumento) -> s.PastaSaida:
        n = self.db.scalar(
            sa.select(sa.func.count()).where(m.DocumentoFinanceiro.pasta_id == p.id)
        )
        return s.PastaSaida.model_validate(p).model_copy(update={"documentos": n or 0})

    @staticmethod
    def _saida(d: m.DocumentoFinanceiro, a: Arquivo | None) -> s.DocumentoSaida:
        return s.DocumentoSaida(
            id=d.id,
            pasta_id=d.pasta_id,
            nome=d.nome,
            arquivo_id=d.arquivo_id,
            arquivo_nome=a.nome if a else "",
            tipo_mime=a.tipo_mime if a else "",
            tamanho=a.tamanho if a else 0,
            criado_em=d.criado_em,
            atualizado_em=d.atualizado_em,
        )

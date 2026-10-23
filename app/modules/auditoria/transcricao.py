"""Transcrição dos vídeos das auditorias no próprio servidor (Whisper, via
faster-whisper, em CPU). Roda fora da API, num processo próprio que consome
as filas de todas as imobiliárias (`python gerenciar.py transcrever`), para
não deixar o sistema lento.

O modelo é baixado na primeira execução e fica em cache no servidor.
Modelos maiores transcrevem melhor e gastam mais memória/tempo:
tiny < base < small < medium (TRANSCRICAO_MODELO no .env)."""

import gc
import logging
import time
from collections.abc import Callable, Iterable
from typing import Protocol

import sqlalchemy as sa
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.imobiliarias import Imobiliaria, usar
from app.core.tempo import agora
from app.modules.arquivos.services import caminho as caminho_arquivo
from app.modules.auditoria.enums import StatusTranscricao, TipoMidia
from app.modules.auditoria.models import MidiaAuditoria

log = logging.getLogger("transcricao")


class Transcritor(Protocol):
    def transcrever(self, caminho: str) -> str: ...


class Whisper:
    """faster-whisper em CPU (int8). Carregado uma vez por processo."""

    def __init__(self, modelo: str, threads: int):
        from faster_whisper import WhisperModel  # dependência só do servidor

        self._modelo = WhisperModel(modelo, device="cpu", compute_type="int8", cpu_threads=threads)

    def transcrever(self, caminho: str) -> str:
        segmentos, _ = self._modelo.transcribe(
            caminho, language="pt", vad_filter=True, beam_size=1,
            condition_on_previous_text=False,
        )  # fmt: skip
        return " ".join(s.text.strip() for s in segmentos).strip()


def proximo(db: Session) -> MidiaAuditoria | None:
    return db.scalar(
        sa.select(MidiaAuditoria)
        .where(MidiaAuditoria.transcricao_status == StatusTranscricao.pendente,
               MidiaAuditoria.tipo == TipoMidia.video)
        .order_by(MidiaAuditoria.criado_em)
        .limit(1)
    )  # fmt: skip


def processar(db: Session, transcritor: Transcritor, midia: MidiaAuditoria) -> None:
    midia.transcricao_status = StatusTranscricao.processando
    db.commit()
    try:
        arquivo = caminho_arquivo(midia.arquivo_id)
        if not arquivo.is_file():
            raise FileNotFoundError("arquivo do vídeo não encontrado no servidor")
        texto = transcritor.transcrever(str(arquivo))
        midia.transcricao_texto = texto or "(sem fala identificada no vídeo)"
        midia.transcricao_status = StatusTranscricao.concluida
        midia.transcricao_erro = ""
    except Exception as e:  # noqa: BLE001 - registra o erro na própria mídia
        log.exception("Falha ao transcrever %s", midia.id)
        midia.transcricao_status = StatusTranscricao.erro
        midia.transcricao_erro = f"Não foi possível transcrever: {e}"[:500]
    midia.transcricao_em = agora()
    db.commit()


def recuperar_interrompidas(db: Session) -> int:
    """Se o processo caiu no meio, devolve à fila o que estava em andamento."""
    presas = db.scalars(
        sa.select(MidiaAuditoria).where(
            MidiaAuditoria.transcricao_status == StatusTranscricao.processando
        )
    ).all()
    for midia in presas:
        midia.transcricao_status = StatusTranscricao.pendente
    db.commit()
    return len(presas)


def rodar(fontes: Callable[[], Iterable[tuple[Imobiliaria, sessionmaker]]],
          transcritor: Transcritor | None = None, uma_vez: bool = False,
          espera: float = 10, ociosidade: float = 180) -> int:  # fmt: skip
    """Consome as filas de todas as imobiliárias, em rodízio: `fontes()`
    devolve cada uma com a fábrica de sessões do banco dela (relida a cada
    volta, para incluir as novas). Com `uma_vez`, para quando todas esvaziam
    (testes/cron). O modelo carregado aqui é liberado depois de `ociosidade`
    segundos sem vídeos, para devolver a memória à API (o servidor tem pouca
    RAM)."""
    s = get_settings()
    proprio = transcritor is None
    feitas = 0
    ultimo = time.monotonic()
    recuperadas: set[str] = set()
    while True:
        trabalhou = False
        for imob, fabrica_sessao in fontes():
            try:
                with usar(imob), fabrica_sessao() as db:
                    if imob.slug not in recuperadas:
                        recuperar_interrompidas(db)
                        recuperadas.add(imob.slug)
                    midia = proximo(db)
                    if midia is None:
                        continue
                    if transcritor is None:
                        log.info("Carregando o modelo %s...", s.transcricao_modelo)
                        transcritor = Whisper(s.transcricao_modelo, s.transcricao_threads)
                    processar(db, transcritor, midia)
            except sa.exc.SQLAlchemyError:
                # Banco de uma imobiliária fora do ar não para a fila das outras.
                log.exception("Falha no banco da imobiliária %s.", imob.slug)
                continue
            feitas += 1
            trabalhou = True
            ultimo = time.monotonic()
        if trabalhou:
            continue
        if uma_vez:
            return feitas
        if proprio and transcritor is not None and time.monotonic() - ultimo > ociosidade:
            log.info("Fila vazia: liberando o modelo da memória.")
            transcritor = None
            gc.collect()
        time.sleep(espera)

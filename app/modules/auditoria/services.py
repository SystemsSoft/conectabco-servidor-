"""Regras das auditorias em campo."""

import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.errors import NaoEncontrado, RegraNegocio, validar_id
from app.core.sequencias import proximo_valor
from app.core.tempo import agora
from app.modules.arquivos.models import Arquivo
from app.modules.auditoria import models as m
from app.modules.auditoria import schemas as s
from app.modules.auditoria.enums import (
    EstadoItem,
    StatusAuditoria,
    StatusTranscricao,
    TipoMidia,
)
from app.modules.crm.models import Imovel
from app.modules.locacao.models import ContratoLocacao
from app.modules.manutencao import models as man
from app.modules.manutencao.enums import (
    ContextoManutencao,
    OrigemManutencao,
    StatusManutencao,
    TipoManutencao,
)

BLOQUEADA = "Auditoria concluída não pode ser alterada. Reabra para editar."

# Checklist padrão (criado como modelo na primeira consulta).
CHECKLIST_PADRAO = [
    ("Entrada e fachada", ["Portas e fechaduras", "Pintura externa", "Interfone / campainha"]),
    ("Sala", ["Paredes e teto", "Piso", "Janelas e vidros", "Tomadas e interruptores", "Iluminação"]),
    ("Cozinha", ["Bancada e pia", "Torneiras e sifão", "Armários", "Revestimentos", "Ponto de gás"]),
    ("Banheiros", ["Vaso e descarga", "Chuveiro e box", "Pia e torneiras", "Ralos", "Revestimentos"]),
    ("Quartos", ["Paredes e teto", "Piso", "Janelas", "Armários embutidos", "Tomadas e iluminação"]),
    ("Área de serviço", ["Tanque e torneiras", "Ralos", "Pontos de máquina"]),
    ("Instalações", ["Quadro de energia / disjuntores", "Infiltrações e umidade", "Hidrômetro e relógio de luz"]),
]


def _saida(a: m.Auditoria) -> s.AuditoriaSaida:
    return s.AuditoriaSaida(
        **{c.key: getattr(a, c.key) for c in m.Auditoria.__mapper__.columns},
        itens=[s.ItemSaida.model_validate(i) for i in a.itens],
        midias=[
            s.MidiaSaida(
                id=x.id, item_id=x.item_id, referencia=f"arquivo:{x.arquivo_id}",
                tipo=x.tipo, titulo=x.titulo, transcricao_status=x.transcricao_status,
                transcricao_texto=x.transcricao_texto, transcricao_erro=x.transcricao_erro,
                transcricao_em=x.transcricao_em, criado_em=x.criado_em,
            )  # fmt: skip
            for x in a.midias
        ],
    )


def saida(a: m.Auditoria) -> s.AuditoriaSaida:
    return _saida(a)


def buscar(db: Session, id: str) -> m.Auditoria:
    a = db.get(m.Auditoria, validar_id(id))
    if a is None:
        raise NaoEncontrado("Auditoria não encontrada.")
    return a


def _editavel(a: m.Auditoria) -> None:
    if a.status == StatusAuditoria.concluida:
        raise RegraNegocio(BLOQUEADA)


def salvar(db: Session, id: str, e: s.AuditoriaEntrada) -> tuple[m.Auditoria, bool]:
    id = validar_id(id)
    imovel = db.get(Imovel, e.imovel_id)
    if imovel is None:
        raise RegraNegocio("Selecione o imóvel.")
    contrato = db.get(ContratoLocacao, e.contrato_id) if e.contrato_id else None
    if e.contrato_id and contrato is None:
        raise RegraNegocio("Contrato não encontrado.")
    if contrato and contrato.imovel_id != imovel.id:
        raise RegraNegocio("O contrato escolhido é de outro imóvel.")
    if e.status == StatusAuditoria.concluida:
        raise RegraNegocio("Use \"Concluir\" para encerrar a auditoria.")
    a = db.get(m.Auditoria, id)
    nova = a is None
    if nova:
        a = m.Auditoria(id=id, numero=f"AUD-{proximo_valor(db, 'auditoria'):04d}")
        db.add(a)
    else:
        _editavel(a)
    for campo, valor in e.model_dump(exclude={"itens"}).items():
        setattr(a, campo, valor)
    # Proprietário: o do imóvel ou, sem ele, o 1º beneficiário do contrato.
    a.proprietario_id = imovel.proprietario_id or (
        contrato.beneficiarios[0].contato_id if contrato and contrato.beneficiarios else None
    )
    existentes = {i.id: i for i in a.itens}
    itens = []
    for ordem, i in enumerate(e.itens):
        if not i.area.strip() or not i.item.strip():
            raise RegraNegocio("Informe a área e o item do checklist.")
        item = existentes.get(i.id) or m.ItemAuditoria(id=validar_id(i.id))
        item.ordem, item.area, item.item = ordem, i.area.strip(), i.item.strip()
        item.estado, item.observacao = i.estado, i.observacao.strip()
        itens.append(item)
    a.itens = itens
    db.commit()
    return a, nova


def remover(db: Session, id: str) -> None:
    a = buscar(db, id)
    _editavel(a)
    db.delete(a)
    db.commit()


def concluir(db: Session, id: str, publicar: bool, usuario_id: str) -> m.Auditoria:
    a = buscar(db, id)
    _editavel(a)
    if not a.itens:
        raise RegraNegocio("Inclua ao menos um item no checklist.")
    pendentes = [i for i in a.itens if i.estado == EstadoItem.pendente]
    if pendentes:
        raise RegraNegocio(f"Avalie todos os itens do checklist ({len(pendentes)} sem avaliação).")
    if a.nota is None:
        raise RegraNegocio("Dê a nota de conservação (1 a 5).")
    a.status = StatusAuditoria.concluida
    a.data_realizada = a.data_realizada or agora().date()
    a.concluida_em = agora()
    a.concluida_por_id = usuario_id
    a.publicada = publicar
    db.commit()
    return a


def reabrir(db: Session, id: str) -> m.Auditoria:
    a = buscar(db, id)
    if a.status != StatusAuditoria.concluida:
        raise RegraNegocio("Só auditorias concluídas podem ser reabertas.")
    a.status = StatusAuditoria.emAndamento
    a.publicada = False
    a.concluida_em = None
    a.concluida_por_id = None
    db.commit()
    return a


def publicar(db: Session, id: str, publicada: bool) -> m.Auditoria:
    a = buscar(db, id)
    if publicada and a.status != StatusAuditoria.concluida:
        raise RegraNegocio("Conclua a auditoria antes de publicá-la para o proprietário.")
    a.publicada = publicada
    db.commit()
    return a


def gerar_manutencoes(db: Session, id: str) -> tuple[m.Auditoria, int]:
    """Cada item com "Problema" vira uma manutenção pendente na pauta."""
    a = buscar(db, id)
    criadas = 0
    for i in a.itens:
        if i.estado != EstadoItem.problema or i.manutencao_id:
            continue
        mt = man.Manutencao(
            id=str(uuid.uuid4()), contexto=ContextoManutencao.locacao, imovel_id=a.imovel_id,
            tipo=TipoManutencao.outros, tipo_outro=f"Auditoria {a.numero}"[:100],
            descricao=f"{i.area} – {i.item}" + (f": {i.observacao}" if i.observacao else ""),
            status=StatusManutencao.pendente, contrato_id=a.contrato_id,
            origem=OrigemManutencao.equipe,
        )  # fmt: skip
        db.add(mt)
        i.manutencao_id = mt.id
        criadas += 1
    if not criadas:
        raise RegraNegocio("Nenhum item com \"Problema\" sem manutenção.")
    db.commit()
    return a, criadas


# ----------------------------------------------------------------- Mídias


def salvar_midia(db: Session, id: str, midia_id: str, e: s.MidiaEntrada) -> m.Auditoria:
    a = buscar(db, id)
    _editavel(a)
    arquivo_id = e.referencia.removeprefix("arquivo:")
    arquivo = db.get(Arquivo, arquivo_id)
    if arquivo is None:
        raise RegraNegocio("Envie o arquivo antes de anexá-lo.")
    if arquivo.categoria != e.tipo.value:
        raise RegraNegocio("O arquivo enviado não é do tipo informado (foto/vídeo).")
    if e.item_id and e.item_id not in {i.id for i in a.itens}:
        raise RegraNegocio("Item do checklist não encontrado.")
    midia = db.get(m.MidiaAuditoria, validar_id(midia_id))
    if midia is None:
        midia = m.MidiaAuditoria(id=midia_id, auditoria_id=a.id)
        db.add(midia)
    elif midia.auditoria_id != a.id:
        raise NaoEncontrado("Mídia não encontrada.")
    midia.arquivo_id, midia.tipo, midia.titulo, midia.item_id = (
        arquivo_id, e.tipo, e.titulo.strip(), e.item_id,
    )  # fmt: skip
    db.commit()
    db.refresh(a)
    return a


def _midia(db: Session, a: m.Auditoria, midia_id: str) -> m.MidiaAuditoria:
    midia = db.get(m.MidiaAuditoria, midia_id)
    if midia is None or midia.auditoria_id != a.id:
        raise NaoEncontrado("Mídia não encontrada.")
    return midia


def remover_midia(db: Session, id: str, midia_id: str) -> m.Auditoria:
    a = buscar(db, id)
    _editavel(a)
    db.delete(_midia(db, a, midia_id))
    db.commit()
    db.refresh(a)
    return a


def pedir_transcricao(db: Session, id: str, midia_id: str) -> m.Auditoria:
    """Põe o vídeo na fila de transcrição (vale também para auditoria já
    concluída: o texto só complementa o relatório)."""
    a = buscar(db, id)
    midia = _midia(db, a, midia_id)
    if midia.tipo != TipoMidia.video:
        raise RegraNegocio("Só vídeos podem ser transcritos.")
    if midia.transcricao_status in (StatusTranscricao.pendente, StatusTranscricao.processando):
        raise RegraNegocio("Este vídeo já está na fila de transcrição.")
    midia.transcricao_status = StatusTranscricao.pendente
    midia.transcricao_erro = ""
    db.commit()
    db.refresh(a)
    return a


# --------------------------------------------------------- Configurações


def configuracao(db: Session) -> s.ConfiguracaoAuditoria:
    r = db.get(m.ConfiguracaoAuditoria, 1)
    return s.ConfiguracaoAuditoria.model_validate((r.dados if r else {}) or {})


def salvar_configuracao(db: Session, c: s.ConfiguracaoAuditoria) -> s.ConfiguracaoAuditoria:
    r = db.get(m.ConfiguracaoAuditoria, 1)
    if r is None:
        r = m.ConfiguracaoAuditoria(id=1)
        db.add(r)
    r.dados = c.model_dump()
    db.commit()
    return c


def modelos(db: Session) -> list[m.ModeloChecklist]:
    lista = list(db.scalars(sa.select(m.ModeloChecklist).order_by(m.ModeloChecklist.nome)))
    if not lista:
        padrao = m.ModeloChecklist(
            id=str(uuid.uuid4()), nome="Vistoria residencial (padrão)", padrao=True,
            itens=[{"area": area, "item": i} for area, itens in CHECKLIST_PADRAO for i in itens],
        )  # fmt: skip
        db.add(padrao)
        db.commit()
        lista = [padrao]
    return lista


def salvar_modelo(db: Session, id: str, e: s.ModeloChecklist) -> m.ModeloChecklist:
    if not e.nome.strip():
        raise RegraNegocio("Informe o nome do modelo.")
    if not e.itens:
        raise RegraNegocio("Inclua ao menos um item no modelo.")
    modelo = db.get(m.ModeloChecklist, validar_id(id))
    if modelo is None:
        modelo = m.ModeloChecklist(id=id)
        db.add(modelo)
    if e.padrao:
        for outro in db.scalars(sa.select(m.ModeloChecklist).where(m.ModeloChecklist.id != id)):
            outro.padrao = False
    modelo.nome, modelo.padrao = e.nome.strip(), e.padrao
    modelo.itens = [i.model_dump() for i in e.itens]
    db.commit()
    return modelo

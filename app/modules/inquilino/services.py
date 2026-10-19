"""Portal do inquilino: acesso, dados do contrato, pagamentos, chamados,
envios de fotos/vídeos e comunicados. Tudo lido das mesmas tabelas da
gestão (contratos, cobranças, manutenção), sem cópia de dados."""

import re
from datetime import date
import uuid
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.errors import NaoEncontrado, RegraNegocio
from app.core.tempo import agora
from app.modules.arquivos import services as arquivos
from app.modules.crm import models as crm
from app.modules.crm.enums import Prioridade, TipoEvento
from app.modules.inquilino import models as m
from app.modules.inquilino.enums import OrigemArquivo, TipoArquivoContrato
from app.modules.locacao import models as loc
from app.modules.locacao.enums import StatusCobranca, StatusContrato
from app.modules.manutencao import models as man
from app.modules.manutencao.enums import (
    ContextoManutencao,
    OrigemManutencao,
    StatusManutencao,
    TipoManutencao,
)

from app.core import acesso_portal as portal

TENTATIVAS = portal.TENTATIVAS
SESSAO_HORAS = portal.SESSAO_HORAS
MAX_ARQUIVOS_POR_ENVIO = 10
TIPO = "inquilino"
digitos = portal.digitos


# ------------------------------------------------------------------ Acesso


def liberar_acesso(db: Session, contato_id: str) -> tuple[m.AcessoInquilino, str]:
    """Cria (ou renova) o acesso com senha provisória. Devolve a senha uma
    única vez, para a equipe entregar ao inquilino."""
    contato = portal.obter_contato(db, contato_id)
    portal.exigir_documento(contato, "locatário")
    if not db.scalar(
        sa.select(sa.func.count())
        .select_from(loc.ContratoLocacao)
        .where(loc.ContratoLocacao.locatario_id == contato_id)
    ):
        raise RegraNegocio("Este contato não é locatário de nenhum contrato.")
    return portal.liberar(db, m.AcessoInquilino, contato, "locatário")


def revogar_acesso(db: Session, contato_id: str) -> None:
    portal.revogar(db, m.AcessoInquilino, contato_id)


def autenticar(db: Session, login: str, senha: str) -> m.AcessoInquilino:
    return portal.autenticar(db, m.AcessoInquilino, login, senha)


def trocar_senha(db: Session, acesso: m.AcessoInquilino, atual: str, nova: str, repetida: str) -> None:
    portal.trocar_senha(db, acesso, atual, nova, repetida)


def criar_token(acesso: m.AcessoInquilino) -> str:
    return portal.criar_token(acesso, TIPO)


def acesso_do_token(db: Session, token: str | None) -> m.AcessoInquilino | None:
    return portal.acesso_do_token(db, m.AcessoInquilino, token, TIPO)


def token_csrf(acesso: m.AcessoInquilino) -> str:
    return portal.token_csrf(acesso, TIPO)


# --------------------------------------------------------------- Contratos


def contratos_do(db: Session, acesso: m.AcessoInquilino) -> list[loc.ContratoLocacao]:
    """Ativos primeiro; encerrados continuam consultáveis (histórico)."""
    contratos = db.scalars(
        sa.select(loc.ContratoLocacao)
        .where(loc.ContratoLocacao.locatario_id == acesso.contato_id)
        .order_by(loc.ContratoLocacao.data_inicio.desc())
    ).all()
    return sorted(contratos, key=lambda c: c.status != StatusContrato.ativo)


def contrato_do(db: Session, acesso: m.AcessoInquilino, contrato_id: str | None) -> loc.ContratoLocacao:
    contratos = contratos_do(db, acesso)
    if not contratos:
        raise NaoEncontrado("Nenhum contrato encontrado para o seu cadastro.")
    if contrato_id is None:
        return contratos[0]
    for c in contratos:
        if c.id == contrato_id:
            return c
    raise NaoEncontrado("Contrato não encontrado.")


# ------------------------------------------------------------- Pagamentos


@dataclass
class Parcela:
    cobranca: loc.Cobranca
    total: float
    situacao: str  # "aberta", "vencida", "paga", "cancelada"
    dias_atraso: int = 0
    estimativa: float | None = None  # valor com multa e juros até hoje


def parcelas(db: Session, contrato: loc.ContratoLocacao, hoje: date | None = None) -> list[Parcela]:
    hoje = hoje or agora().date()
    cobrancas = db.scalars(
        sa.select(loc.Cobranca)
        .where(loc.Cobranca.contrato_id == contrato.id)
        .order_by(loc.Cobranca.vencimento.desc())
    ).all()
    lista = []
    for c in cobrancas:
        total = round(sum(i.valor for i in c.itens), 2)
        if c.status == StatusCobranca.paga:
            lista.append(Parcela(c, total, "paga"))
        elif c.status == StatusCobranca.cancelada:
            lista.append(Parcela(c, total, "cancelada"))
        elif c.vencimento < hoje:
            dias = (hoje - c.vencimento).days
            multa = total * contrato.multa_atraso / 100
            juros = total * contrato.juros_mes / 100 / 30 * dias
            lista.append(Parcela(c, total, "vencida", dias, round(total + multa + juros, 2)))
        else:
            lista.append(Parcela(c, total, "aberta"))
    return lista


def resumo_pagamentos(lista: list[Parcela], hoje: date | None = None) -> dict:
    hoje = hoje or agora().date()
    abertas = [p for p in lista if p.situacao in ("aberta", "vencida")]
    pagas = [p for p in lista if p.situacao == "paga"]
    proximas = sorted((p for p in abertas if p.situacao == "aberta"), key=lambda p: p.cobranca.vencimento)
    return {
        "em_aberto": round(sum(p.total for p in abertas), 2),
        "vencidas": sum(p.situacao == "vencida" for p in abertas),
        "proxima": proximas[0] if proximas else None,
        "pago_no_ano": round(sum(
            p.cobranca.valor_pago or p.total for p in pagas
            if p.cobranca.data_pagamento and p.cobranca.data_pagamento.year == hoje.year
        ), 2),
        "qtd_pagas": len(pagas),
    }  # fmt: skip


def _ascii(texto: str, limite: int) -> str:
    sem = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9 ]", "", sem).upper().strip()[:limite] or "NA"


def _campo(id_: str, valor: str) -> str:
    return f"{id_}{len(valor):02d}{valor}"


def _crc16(dados: str) -> str:
    crc = 0xFFFF
    for byte in dados.encode():
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else crc << 1
            crc &= 0xFFFF
    return f"{crc:04X}"


def pix_copia_e_cola(chave: str, nome: str, cidade: str, valor: float, txid: str) -> str:
    """BR Code estático do PIX (padrão do Banco Central)."""
    conta = _campo("00", "br.gov.bcb.pix") + _campo("01", chave.strip())
    corpo = (
        _campo("00", "01")
        + _campo("26", conta)
        + _campo("52", "0000")
        + _campo("53", "986")
        + _campo("54", f"{valor:.2f}")
        + _campo("58", "BR")
        + _campo("59", _ascii(nome, 25))
        + _campo("60", _ascii(cidade, 15))
        + _campo("62", _campo("05", re.sub(r"[^A-Za-z0-9]", "", txid)[:25] or "***"))
        + "6304"
    )
    return corpo + _crc16(corpo)


def cidade_da_empresa(endereco: str, padrao: str) -> str:
    """'Rua X, 100 - Icaraí, Niterói/RJ' -> 'Niterói'."""
    achado = re.search(r"([^,\-]+)/[A-Z]{2}\s*$", endereco or "")
    return achado.group(1).strip() if achado else padrao


# --------------------------------------------------------- Arquivos e mídia


def arquivos_visiveis(db: Session, contrato: loc.ContratoLocacao) -> list[m.ArquivoContrato]:
    return list(db.scalars(
        sa.select(m.ArquivoContrato)
        .where(m.ArquivoContrato.contrato_id == contrato.id, m.ArquivoContrato.visivel_inquilino.is_(True))
        .order_by(m.ArquivoContrato.criado_em.desc())
    ))  # fmt: skip


def arquivo_do_inquilino(db: Session, acesso: m.AcessoInquilino, id_: str) -> tuple[m.ArquivoContrato, Path, str, str]:
    """Só arquivos visíveis de contratos do próprio inquilino."""
    a = db.get(m.ArquivoContrato, id_)
    ids = {c.id for c in contratos_do(db, acesso)}
    if a is None or a.contrato_id not in ids or not a.visivel_inquilino:
        raise NaoEncontrado("Arquivo não encontrado.")
    from app.modules.arquivos.models import Arquivo

    original = db.get(Arquivo, a.arquivo_id)
    caminho = arquivos.caminho(a.arquivo_id)
    if original is None or not caminho.is_file():
        raise NaoEncontrado("Arquivo não encontrado.")
    return a, caminho, original.tipo_mime, original.nome


def categorias(db: Session, itens: list[m.ArquivoContrato]) -> dict[str, str]:
    """foto/vídeo/arquivo de cada item (para a miniatura certa)."""
    from app.modules.arquivos.models import Arquivo

    ids = {a.arquivo_id: a.id for a in itens}
    if not ids:
        return {}
    linhas = db.execute(sa.select(Arquivo.id, Arquivo.categoria).where(Arquivo.id.in_(ids)))
    return {ids[i]: cat for i, cat in linhas}


def _categoria(nome: str) -> str:
    ext = nome.rsplit(".", 1)[-1].lower() if "." in nome else ""
    if ext in arquivos.CATEGORIAS["video"][0]:
        return "video"
    if ext in arquivos.CATEGORIAS["foto"][0]:
        return "foto"
    raise RegraNegocio(f'"{nome}": envie fotos (JPG, PNG, WEBP) ou vídeos (MP4, MOV, WEBM).')


def _guardar_midias(db, contrato, envios, tipo, titulo, observacao, manutencao_id=None) -> list[m.ArquivoContrato]:
    envios = [e for e in envios if e and e[0]]
    if len(envios) > MAX_ARQUIVOS_POR_ENVIO:
        raise RegraNegocio(f"Envie até {MAX_ARQUIVOS_POR_ENVIO} arquivos por vez.")
    for nome, _ in envios:
        _categoria(nome)  # confere todos antes de gravar qualquer um
    salvos = []
    for i, (nome, conteudo) in enumerate(envios, 1):
        arq = arquivos.salvar(db, conteudo, nome, _categoria(nome), None)
        registro = m.ArquivoContrato(
            id=str(uuid.uuid4()), contrato_id=contrato.id, manutencao_id=manutencao_id,
            tipo=tipo, origem=OrigemArquivo.inquilino,
            titulo=(titulo if len(envios) == 1 else f"{titulo} ({i})")[:200],
            observacao=observacao, arquivo_id=arq.id, visivel_inquilino=True,
        )  # fmt: skip
        db.add(registro)
        salvos.append(registro)
    db.commit()
    return salvos


def enviar_estado_imovel(db, contrato, descricao: str, envios) -> list[m.ArquivoContrato]:
    if not [e for e in envios if e and e[0]]:
        raise RegraNegocio("Escolha ao menos uma foto ou vídeo.")
    salvos = _guardar_midias(
        db, contrato, envios, TipoArquivoContrato.estadoImovel,
        "Estado do imóvel", descricao.strip()[:2000],
    )  # fmt: skip
    _tarefa_equipe(
        db, contrato, f"Inquilino enviou {len(salvos)} foto(s)/vídeo(s) do imóvel",
        descricao or "Fotos/vídeos do estado do imóvel enviados pelo portal.",
    )  # fmt: skip
    db.commit()
    return salvos


# ---------------------------------------------------------------- Chamados


def chamados(db: Session, contrato: loc.ContratoLocacao) -> list[man.Manutencao]:
    return list(db.scalars(
        sa.select(man.Manutencao)
        .where(man.Manutencao.contrato_id == contrato.id)
        .order_by(man.Manutencao.criado_em.desc())
    ))  # fmt: skip


def abrir_chamado(db, contrato, tipo: str, descricao: str, envios) -> man.Manutencao:
    if contrato.status != StatusContrato.ativo:
        raise RegraNegocio("Chamados só podem ser abertos em contratos ativos.")
    descricao = descricao.strip()
    if len(descricao) < 10:
        raise RegraNegocio("Descreva o problema com um pouco mais de detalhe.")
    tp = TipoManutencao(tipo) if tipo in TipoManutencao._value2member_map_ else TipoManutencao.outros
    chamado = man.Manutencao(
        id=str(uuid.uuid4()), contexto=ContextoManutencao.locacao,
        imovel_id=contrato.imovel_id, tipo=tp,
        tipo_outro="Chamado do inquilino" if tp == TipoManutencao.outros else "",
        descricao=descricao[:5000], status=StatusManutencao.pendente,
        contrato_id=contrato.id, origem=OrigemManutencao.inquilino,
    )  # fmt: skip
    db.add(chamado)
    db.flush()
    _guardar_midias(db, contrato, envios, TipoArquivoContrato.chamado, "Foto do chamado", "", chamado.id)
    _tarefa_equipe(
        db, contrato, f"Chamado de manutenção ({tp.rotulo}) – contrato {contrato.numero}", descricao
    )
    db.commit()
    return chamado


def anexos_do_chamado(db: Session, chamado_id: str) -> list[m.ArquivoContrato]:
    return list(db.scalars(
        sa.select(m.ArquivoContrato).where(m.ArquivoContrato.manutencao_id == chamado_id)
    ))  # fmt: skip


def _tarefa_equipe(db: Session, contrato, titulo: str, descricao: str) -> None:
    """Avisa a equipe na Central de Relacionamento."""
    db.add(crm.Evento(
        id=str(uuid.uuid4()), titulo=f"Portal: {titulo}"[:200], tipo=TipoEvento.recado,
        descricao=descricao[:5000], data_hora=agora(), prioridade=Prioridade.alta,
        contato_id=contrato.locatario_id, imovel_id=contrato.imovel_id,
    ))  # fmt: skip


def avisar_andamento_chamado(db: Session, chamado: man.Manutencao) -> None:
    """Chamado mudou de status na gestão: o inquilino recebe um aviso."""
    texto = {
        StatusManutencao.pendente: "voltou para a fila de atendimento",
        StatusManutencao.emAndamento: "está em andamento",
        StatusManutencao.concluida: "foi concluído",
    }[chamado.status]
    previsto = f" Previsão: {chamado.data_prevista:%d/%m/%Y}." if chamado.data_prevista else ""
    avisar(db, chamado.contrato_id, "Atualização do seu chamado",
           f'Seu chamado "{chamado.descricao[:80]}" {texto}.{previsto}')  # fmt: skip


# ------------------------------------------------------------ Comunicados


def avisar(db: Session, contrato_id: str | None, titulo: str, mensagem: str,
           automatico: bool = True, enviado_por_id: str | None = None) -> m.Comunicado:  # fmt: skip
    c = m.Comunicado(
        id=str(uuid.uuid4()), contrato_id=contrato_id, titulo=titulo[:200],
        mensagem=mensagem, automatico=automatico, enviado_por_id=enviado_por_id,
    )  # fmt: skip
    db.add(c)
    return c


def comunicados_do(db: Session, acesso: m.AcessoInquilino) -> list[tuple[m.Comunicado, bool]]:
    """Avisos dos contratos do inquilino e os gerais; com "lido"."""
    ids = [c.id for c in contratos_do(db, acesso)]
    lidos = set(db.scalars(
        sa.select(m.LeituraComunicado.comunicado_id).where(m.LeituraComunicado.acesso_id == acesso.id)
    ))  # fmt: skip
    avisos = db.scalars(
        sa.select(m.Comunicado)
        .where(sa.or_(m.Comunicado.contrato_id.in_(ids), m.Comunicado.contrato_id.is_(None)))
        .order_by(m.Comunicado.criado_em.desc())
        .limit(200)
    ).all()
    return [(c, c.id in lidos) for c in avisos]


def marcar_lidos(db: Session, acesso: m.AcessoInquilino, avisos: list[m.Comunicado]) -> None:
    ja = set(db.scalars(
        sa.select(m.LeituraComunicado.comunicado_id).where(m.LeituraComunicado.acesso_id == acesso.id)
    ))  # fmt: skip
    for c in avisos:
        if c.id not in ja:
            db.add(m.LeituraComunicado(comunicado_id=c.id, acesso_id=acesso.id))
    db.commit()


def site_seguro() -> bool:
    return get_settings().site_url.startswith("https://")

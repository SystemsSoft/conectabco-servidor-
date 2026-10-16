"""Regras do site público: configuração, imóveis publicados e leads."""

import re
import time
import uuid
from collections import defaultdict, deque

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.errors import RegraNegocio
from app.core.tempo import agora
from app.modules.crm import models as crm
from app.modules.crm.enums import (
    AnexoTipo,
    EtapaFunil,
    OrigemContato,
    PapelContato,
    Prioridade,
    StatusImovel,
    TipoEvento,
)
from app.modules.equipe import models as equipe
from app.modules.equipe.enums import (
    ModuloSistema,
    OrigemAtendimento,
    StatusFila,
    TipoAtividade,
)
from app.modules.site import models as m
from app.modules.site import schemas as s
from app.modules.site.enums import StatusLead, TipoLead

# ------------------------------------------------------------ Configuração


def configuracao(db: Session) -> s.ConfiguracaoSite:
    registro = db.get(m.ConfiguracaoSite, 1)
    return s.ConfiguracaoSite.model_validate((registro.dados if registro else {}) or {})


def salvar_configuracao(db: Session, cfg: s.ConfiguracaoSite) -> s.ConfiguracaoSite:
    cfg = cfg.model_copy(update={"whatsapp": _digitos(cfg.whatsapp)})
    if cfg.whatsapp and len(cfg.whatsapp) not in (10, 11, 12, 13):
        raise RegraNegocio("WhatsApp inválido: informe DDD e número.")
    for rede, url in (("Instagram", cfg.instagram), ("Facebook", cfg.facebook)):
        if url and not url.startswith("https://"):
            raise RegraNegocio(f"Link do {rede} deve começar com https://")
    registro = db.get(m.ConfiguracaoSite, 1)
    if registro is None:
        registro = m.ConfiguracaoSite(id=1)
        db.add(registro)
    registro.dados = cfg.model_dump()
    db.commit()
    return cfg


def contatos_do_site(db: Session, cfg: s.ConfiguracaoSite) -> dict:
    """Contatos exibidos: os do site ou, em branco, os da imobiliária."""
    from app.modules.personalizacao.models import DadosEmpresa

    e = db.get(DadosEmpresa, 1)
    empresa = {
        "nome": e.nome if e else "Marcelo Bonifácio",
        "atividade": e.atividade if e else "Corretor de Imóveis",
        "creci": e.creci if e else "CRECI 065655 RJ",
        "documento": e.documento if e else "",
        "tem_logo": bool(e and e.logo),
    }
    telefone = cfg.telefone or (e.telefone if e else "")
    whatsapp = cfg.whatsapp or _digitos(telefone)
    if whatsapp and len(whatsapp) <= 11:
        whatsapp = "55" + whatsapp  # wa.me pede o código do país
    return empresa | {
        "telefone": telefone,
        "whatsapp": whatsapp if len(whatsapp) >= 12 else "",
        "email": cfg.email or (e.email if e else ""),
        "endereco": cfg.endereco or (e.endereco if e else ""),
    }


# ------------------------------------------------------- Imóveis públicos


def _publicado():
    return sa.and_(
        crm.Imovel.publicar_site.is_(True),
        crm.Imovel.status == StatusImovel.disponivel,
    )


def imoveis_publicados(db: Session) -> list[crm.Imovel]:
    return list(
        db.scalars(
            sa.select(crm.Imovel).where(_publicado()).order_by(crm.Imovel.criado_em.desc())
        )
    )


def imovel_publicado(db: Session, codigo: str) -> crm.Imovel | None:
    return db.scalar(
        sa.select(crm.Imovel).where(_publicado(), crm.Imovel.codigo == codigo.upper())
    )


def midia_publica(db: Session, arquivo_id: str) -> bool:
    """Só fotos e vídeos de imóveis publicados ficam abertos ao público."""
    return (
        db.scalar(
            sa.select(sa.func.count())
            .select_from(crm.Anexo)
            .join(crm.Imovel, crm.Imovel.id == crm.Anexo.imovel_id)
            .where(
                crm.Anexo.url == f"arquivo:{arquivo_id}",
                crm.Anexo.tipo.in_([AnexoTipo.foto, AnexoTipo.video]),
                _publicado(),
            )
        )
        > 0
    )


# ------------------------------------------------------------------- Leads

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_envios: dict[str, deque] = defaultdict(deque)
LIMITE_ENVIOS = (5, 600)  # 5 envios a cada 10 minutos por endereço


def _digitos(texto: str) -> str:
    return re.sub(r"\D", "", texto or "")


def _formatar_telefone(digitos: str) -> str:
    if len(digitos) == 11:
        return f"({digitos[:2]}) {digitos[2:7]}-{digitos[7:]}"
    if len(digitos) == 10:
        return f"({digitos[:2]}) {digitos[2:6]}-{digitos[6:]}"
    return digitos


def conferir_limite(origem: str) -> None:
    """Evita robôs enchendo a caixa de leads (só envios aceitos contam:
    quem errou um campo pode corrigir e reenviar)."""
    maximo, janela = LIMITE_ENVIOS
    agora_s = time.monotonic()
    fila = _envios[origem]
    while fila and agora_s - fila[0] > janela:
        fila.popleft()
    if len(fila) >= maximo:
        raise RegraNegocio(
            "Recebemos várias mensagens seguidas. Tente de novo em alguns minutos "
            "ou fale com a gente pelo WhatsApp."
        )


def contar_envio(origem: str) -> None:
    _envios[origem].append(time.monotonic())


def _contato_existente(db: Session, email: str, telefone: str) -> crm.Contato | None:
    if email:
        c = db.scalar(
            sa.select(crm.Contato).where(sa.func.lower(crm.Contato.email) == email)
        )
        if c:
            return c
    if len(telefone) >= 8:
        fim = telefone[-4:]
        candidatos = db.scalars(
            sa.select(crm.Contato).where(
                sa.or_(
                    crm.Contato.celular.like(f"%{fim}"),
                    crm.Contato.telefone.like(f"%{fim}"),
                )
            )
        )
        for c in candidatos:
            if telefone in (_digitos(c.celular), _digitos(c.telefone)):
                return c
    return None


def _contato_do_lead(db: Session, e: s.LeadEntrada, telefone: str) -> crm.Contato:
    papel = PapelContato.proprietario if e.tipo == TipoLead.anunciar else PapelContato.lead
    c = _contato_existente(db, e.email, telefone)
    if c is None:
        c = crm.Contato(
            id=str(uuid.uuid4()),
            nome=e.nome,
            email=e.email,
            celular=_formatar_telefone(telefone),
            origem=OrigemContato.site,
            etapa=EtapaFunil.novo,
            aceita_contato=e.consentimento,
            observacoes="Cadastrado pelo site.",
        )
        db.add(c)
    else:
        c.email = c.email or e.email
        if not (c.celular or c.telefone):
            c.celular = _formatar_telefone(telefone)
    if papel not in {p.papel for p in c.papeis}:
        c.papeis.append(crm.ContatoPapel(papel=papel))
    return c


def _chamar_proximo(db: Session) -> equipe.Usuario | None:
    """Mesma regra do app: o primeiro disponível fica em atendimento e vai
    para o fim da fila."""
    fila = list(db.scalars(sa.select(equipe.ItemFila).order_by(equipe.ItemFila.posicao)))
    for item in fila:
        u = db.get(equipe.Usuario, item.usuario_id)
        if item.status == StatusFila.disponivel and u is not None and u.ativo:
            item.status = StatusFila.emAtendimento
            item.desde = agora()
            item.posicao = max(i.posicao for i in fila) + 1
            return u
    return None


def registrar_lead(
    db: Session, e: s.LeadEntrada, cfg: s.ConfiguracaoSite
) -> m.LeadSite:
    e = e.model_copy(
        update={
            "nome": " ".join(e.nome.split()),
            "email": e.email.strip().lower(),
            "mensagem": e.mensagem.strip(),
        }
    )
    telefone = _digitos(e.telefone)
    if len(e.nome) < 2:
        raise RegraNegocio("Informe seu nome.")
    if e.email and not _EMAIL.match(e.email):
        raise RegraNegocio("E-mail inválido.")
    if telefone and len(telefone) not in (10, 11):
        raise RegraNegocio("Telefone inválido: informe DDD e número.")
    if not e.email and not telefone:
        raise RegraNegocio("Informe um telefone ou e-mail para retornarmos.")
    if not e.consentimento:
        raise RegraNegocio("Autorize o contato para enviarmos sua mensagem.")
    if e.tipo == TipoLead.visita and not cfg.permitir_agendar_visita:
        e = e.model_copy(update={"tipo": TipoLead.interesse})
    if e.tipo == TipoLead.visita and e.data_visita and e.data_visita.date() < agora().date():
        raise RegraNegocio("Escolha uma data de visita a partir de hoje.")

    imovel = imovel_publicado(db, e.imovel_codigo) if e.imovel_codigo else None
    contato = _contato_do_lead(db, e, telefone)
    lead = m.LeadSite(
        id=str(uuid.uuid4()),
        tipo=e.tipo,
        status=StatusLead.novo,
        nome=e.nome,
        email=e.email,
        telefone=_formatar_telefone(telefone),
        mensagem=e.mensagem,
        data_visita=e.data_visita if e.tipo == TipoLead.visita else None,
        imovel_id=imovel.id if imovel else None,
        contato_id=contato.id,
        pagina=e.pagina,
    )
    db.add(lead)
    db.flush()

    resumo = "\n".join(
        x
        for x in [
            f"{e.tipo.rotulo} pelo site.",
            f"Imóvel: {imovel.codigo} – {imovel.titulo}" if imovel else "",
            f"Visita desejada: {lead.data_visita:%d/%m/%Y %H:%M}" if lead.data_visita else "",
            f"Telefone: {lead.telefone}" if lead.telefone else "",
            f"E-mail: {lead.email}" if lead.email else "",
            f"Mensagem: {lead.mensagem}" if lead.mensagem else "",
        ]
        if x
    )

    if cfg.distribuir_na_fila and (corretor := _chamar_proximo(db)):
        atendimento = equipe.Atendimento(
            id=str(uuid.uuid4()),
            corretor_id=corretor.id,
            cliente_nome=lead.nome,
            origem=OrigemAtendimento.site,
            iniciado_em=agora(),
            contato_id=contato.id,
            observacao=resumo,
        )
        db.add(atendimento)
        lead.corretor_id = corretor.id
        lead.atendimento_id = atendimento.id
        lead.status = StatusLead.emAtendimento
        if not contato.corretor_responsavel:
            contato.corretor_responsavel = corretor.nome
        db.add(
            equipe.Atividade(
                id=str(uuid.uuid4()),
                usuario_id=corretor.id,
                tipo=TipoAtividade.atendimento,
                descricao=(
                    f"Lead do site ({lead.nome}) encaminhado a {corretor.nome}"
                )[:300],
                modulo=ModuloSistema.site,
            )
        )

    if cfg.criar_tarefa:
        visita = e.tipo == TipoLead.visita and lead.data_visita is not None
        evento = crm.Evento(
            id=str(uuid.uuid4()),
            titulo=f"Site: {e.tipo.rotulo} – {lead.nome}"[:200],
            tipo=TipoEvento.visita if visita else TipoEvento.ligacao,
            descricao=resumo,
            data_hora=lead.data_visita if visita else agora(),
            prioridade=Prioridade.alta,
            contato_id=contato.id,
            imovel_id=lead.imovel_id,
        )
        db.add(evento)
        lead.evento_id = evento.id

    db.commit()
    return lead


def atualizar_lead(db: Session, lead: m.LeadSite, e: s.LeadAtualizacao) -> m.LeadSite:
    if e.corretor_id and db.get(equipe.Usuario, e.corretor_id) is None:
        raise RegraNegocio("Corretor não encontrado.")
    lead.status = e.status
    lead.corretor_id = e.corretor_id
    lead.observacao = e.observacao.strip()
    db.commit()
    return lead

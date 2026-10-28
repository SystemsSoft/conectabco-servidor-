from datetime import date, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import BaseCentral
from app.core.ulid import novo_ulid


class Imobiliaria(BaseCentral):
    __tablename__ = "imobiliarias"

    # Identificador curto: cabeçalho X-Imobiliaria, ?imob= e pasta dos arquivos.
    slug: Mapped[str] = mapped_column(sa.String(40), primary_key=True)
    nome: Mapped[str] = mapped_column(sa.String(200))
    # Banco (schema) da imobiliária no servidor MySQL.
    banco: Mapped[str] = mapped_column(sa.String(64), unique=True)
    # Endereço público do site: sitemap, links do QR code e cookie seguro.
    site_url: Mapped[str] = mapped_column(sa.String(200), default="")
    ativa: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    # Paleta do site e do app (#rrggbb; vazia = a padrão, azul-marinho e dourado).
    cor_primaria: Mapped[str] = mapped_column(sa.String(7), default="")
    cor_destaque: Mapped[str] = mapped_column(sa.String(7), default="")
    criada_em: Mapped[datetime] = mapped_column(sa.DateTime)
    # Quando foi desativada (cancelamento); vazio enquanto ativa.
    desativada_em: Mapped[datetime | None] = mapped_column(sa.DateTime)
    # Plano do contrato: mensalidade e dia do vencimento.
    mensalidade: Mapped[Decimal] = mapped_column(sa.Numeric(10, 2), default=Decimal("150.00"))
    dia_vencimento: Mapped[int] = mapped_column(sa.Integer, default=5)
    # ULID fixo e único: prefixo dos arquivos dela (imobiliarias/<chave>/...).
    chave: Mapped[str] = mapped_column(sa.String(26), unique=True, default=novo_ulid)
    dominios: Mapped[list["Dominio"]] = relationship(
        back_populates="imobiliaria",
        cascade="all, delete-orphan",
        order_by="Dominio.dominio",
        lazy="selectin",
    )


class Dominio(BaseCentral):
    """Endereço (site e portais) que abre a imobiliária."""

    __tablename__ = "dominios"

    dominio: Mapped[str] = mapped_column(sa.String(253), primary_key=True)
    imobiliaria_slug: Mapped[str] = mapped_column(
        sa.ForeignKey("imobiliarias.slug", ondelete="CASCADE"), index=True
    )
    imobiliaria: Mapped[Imobiliaria] = relationship(back_populates="dominios")


class Administrador(BaseCentral):
    """Quem entra no painel da plataforma (/plataforma) e cadastra as
    imobiliárias. Não é usuário de nenhuma imobiliária."""

    __tablename__ = "administradores"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    nome: Mapped[str] = mapped_column(sa.String(150))
    login: Mapped[str] = mapped_column(sa.String(60), unique=True)
    senha_hash: Mapped[str] = mapped_column(sa.String(200))
    ativo: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    # Muda a cada troca de senha: derruba as sessões abertas.
    versao: Mapped[int] = mapped_column(sa.Integer, default=1)
    tentativas: Mapped[int] = mapped_column(sa.Integer, default=0)
    bloqueado_ate: Mapped[datetime | None] = mapped_column(sa.DateTime)
    criado_em: Mapped[datetime] = mapped_column(sa.DateTime)
    ultimo_acesso: Mapped[datetime | None] = mapped_column(sa.DateTime)


class Representante(BaseCentral):
    """Representante da associação: entra na área do representante
    (/representante) e envia os corretores para implantação."""

    __tablename__ = "representantes"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    nome: Mapped[str] = mapped_column(sa.String(150))
    login: Mapped[str] = mapped_column(sa.String(60), unique=True)
    email: Mapped[str] = mapped_column(sa.String(200), default="")
    telefone: Mapped[str] = mapped_column(sa.String(30), default="")
    # Cidade, estado ou região em que atua.
    regiao: Mapped[str] = mapped_column(sa.String(150), default="")
    senha_hash: Mapped[str] = mapped_column(sa.String(200))
    ativo: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    # Muda a cada troca de senha: derruba as sessões abertas.
    versao: Mapped[int] = mapped_column(sa.Integer, default=1)
    tentativas: Mapped[int] = mapped_column(sa.Integer, default=0)
    bloqueado_ate: Mapped[datetime | None] = mapped_column(sa.DateTime)
    criado_em: Mapped[datetime] = mapped_column(sa.DateTime)
    ultimo_acesso: Mapped[datetime | None] = mapped_column(sa.DateTime)


class SolicitacaoImplantacao(BaseCentral):
    """Corretor (ou imobiliária) a implantar: enviado por um representante ou
    cadastrado direto no painel. A plataforma acompanha pela situação e, ao
    implantar, liga a solicitação à imobiliária criada."""

    __tablename__ = "solicitacoes_implantacao"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    # Quem cadastrou: um representante ou, no painel, um administrador.
    representante_id: Mapped[str | None] = mapped_column(sa.ForeignKey("representantes.id"), index=True)
    administrador_id: Mapped[str | None] = mapped_column(sa.ForeignKey("administradores.id"))
    # nova, em_andamento, implantada ou recusada.
    situacao: Mapped[str] = mapped_column(sa.String(20), default="nova", index=True)
    # Corretor responsável.
    nome: Mapped[str] = mapped_column(sa.String(150))
    cpf_cnpj: Mapped[str] = mapped_column(sa.String(18))
    creci: Mapped[str] = mapped_column(sa.String(30))
    email: Mapped[str] = mapped_column(sa.String(200))
    telefone: Mapped[str] = mapped_column(sa.String(30))
    # Imobiliária a implantar.
    nome_imobiliaria: Mapped[str] = mapped_column(sa.String(200))
    cidade: Mapped[str] = mapped_column(sa.String(120))
    uf: Mapped[str] = mapped_column(sa.String(2))
    dominio: Mapped[str] = mapped_column(sa.String(253), default="")
    imoveis: Mapped[int | None] = mapped_column(sa.Integer)
    contratos: Mapped[int | None] = mapped_column(sa.Integer)
    usuarios: Mapped[int | None] = mapped_column(sa.Integer)
    observacoes: Mapped[str] = mapped_column(sa.Text, default="")
    # Da plataforma para o representante (aparece na área dele).
    resposta: Mapped[str] = mapped_column(sa.Text, default="")
    imobiliaria_slug: Mapped[str | None] = mapped_column(
        sa.ForeignKey("imobiliarias.slug", ondelete="SET NULL")
    )
    # Financeiro: sem o 1º pagamento confirmado, a Tecnologia não passa a
    # solicitação para "em implantação" nem implanta.
    implantada_em: Mapped[datetime | None] = mapped_column(sa.DateTime)
    primeiro_pagamento_em: Mapped[date | None] = mapped_column(sa.Date)
    primeiro_pagamento_confirmado_em: Mapped[datetime | None] = mapped_column(sa.DateTime)
    primeiro_pagamento_por_id: Mapped[str | None] = mapped_column(sa.ForeignKey("administradores.id"))
    observacao_financeira: Mapped[str] = mapped_column(sa.Text, default="")
    criada_em: Mapped[datetime] = mapped_column(sa.DateTime, index=True)
    atualizada_em: Mapped[datetime] = mapped_column(sa.DateTime)
    representante: Mapped[Representante | None] = relationship(lazy="joined")
    administrador: Mapped[Administrador | None] = relationship(
        lazy="joined", foreign_keys="SolicitacaoImplantacao.administrador_id"
    )
    pagamento_confirmado_por: Mapped[Administrador | None] = relationship(
        lazy="joined", foreign_keys="SolicitacaoImplantacao.primeiro_pagamento_por_id"
    )

    @property
    def pago(self) -> bool:
        return self.primeiro_pagamento_confirmado_em is not None


class DocumentoSolicitacao(BaseCentral):
    """Arquivo do financeiro (boleto de cobrança, comprovante...) de uma
    solicitação. O conteúdo fica no armazenamento, em
    plataforma/solicitacoes/<id da solicitação>/<ULID>."""

    __tablename__ = "documentos_solicitacao"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    solicitacao_id: Mapped[str] = mapped_column(
        sa.ForeignKey("solicitacoes_implantacao.id", ondelete="CASCADE"), index=True
    )
    # boleto, comprovante ou outro.
    tipo: Mapped[str] = mapped_column(sa.String(20))
    nome: Mapped[str] = mapped_column(sa.String(255))
    descricao: Mapped[str] = mapped_column(sa.String(300), default="")
    tipo_mime: Mapped[str] = mapped_column(sa.String(120))
    tamanho: Mapped[int] = mapped_column(sa.BigInteger)
    chave: Mapped[str] = mapped_column(sa.String(160), unique=True)
    enviado_por_id: Mapped[str | None] = mapped_column(sa.ForeignKey("administradores.id"))
    criado_em: Mapped[datetime] = mapped_column(sa.DateTime)
    enviado_por: Mapped[Administrador | None] = relationship(lazy="joined")


class DadosContratante(BaseCentral):
    """Dados do CONTRATANTE no contrato de prestação de serviços da
    associação (um por imobiliária)."""

    __tablename__ = "dados_contratante"

    imobiliaria_slug: Mapped[str] = mapped_column(
        sa.ForeignKey("imobiliarias.slug", ondelete="CASCADE"), primary_key=True
    )
    nome: Mapped[str] = mapped_column(sa.String(150))
    endereco: Mapped[str] = mapped_column(sa.String(200))
    numero: Mapped[str] = mapped_column(sa.String(20))
    bairro: Mapped[str] = mapped_column(sa.String(100))
    cidade: Mapped[str] = mapped_column(sa.String(120))
    uf: Mapped[str] = mapped_column(sa.String(2))
    cpf: Mapped[str] = mapped_column(sa.String(11), default="")
    identidade: Mapped[str] = mapped_column(sa.String(30), default="")
    cnpj: Mapped[str] = mapped_column(sa.String(14), default="")
    creci_pj: Mapped[str] = mapped_column(sa.String(30), default="")
    creci: Mapped[str] = mapped_column(sa.String(30), default="")
    nome_comercial: Mapped[str] = mapped_column(sa.String(200), default="")
    endereco_comercial: Mapped[str] = mapped_column(sa.String(300), default="")
    telefone_1: Mapped[str] = mapped_column(sa.String(30))
    telefone_2: Mapped[str] = mapped_column(sa.String(30), default="")
    # Onde o site e o domínio estão (o endereço do site fica na imobiliária).
    servidor: Mapped[str] = mapped_column(sa.String(150), default="")
    dns: Mapped[str] = mapped_column(sa.String(150), default="")
    instagram: Mapped[str] = mapped_column(sa.String(200), default="")
    facebook: Mapped[str] = mapped_column(sa.String(200), default="")
    tiktok: Mapped[str] = mapped_column(sa.String(200), default="")
    youtube: Mapped[str] = mapped_column(sa.String(200), default="")
    data_implantacao: Mapped[date | None] = mapped_column(sa.Date)
    horario_implantacao: Mapped[str] = mapped_column(sa.String(5), default="")
    data_assinatura: Mapped[date | None] = mapped_column(sa.Date)
    atualizado_em: Mapped[datetime] = mapped_column(sa.DateTime)


class LeadAssociacao(BaseCentral):
    """Pré-cadastro feito no site institucional ("Quero me associar"): o
    Comercial acompanha e, quando avança, converte em solicitação."""

    __tablename__ = "leads_associacao"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    nome: Mapped[str] = mapped_column(sa.String(150))
    email: Mapped[str] = mapped_column(sa.String(200))
    whatsapp: Mapped[str] = mapped_column(sa.String(30))
    creci: Mapped[str] = mapped_column(sa.String(30), default="")
    # Como a pessoa escreveu ("Cidade / UF").
    cidade: Mapped[str] = mapped_column(sa.String(150))
    perfil: Mapped[str] = mapped_column(sa.String(40))
    quer_sistema: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    # novo, em_contato, convertido ou descartado.
    situacao: Mapped[str] = mapped_column(sa.String(20), default="novo", index=True)
    anotacao: Mapped[str] = mapped_column(sa.Text, default="")
    solicitacao_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("solicitacoes_implantacao.id", ondelete="SET NULL")
    )
    criado_em: Mapped[datetime] = mapped_column(sa.DateTime, index=True)
    atualizado_em: Mapped[datetime] = mapped_column(sa.DateTime)


class ContratoDigital(BaseCentral):
    """Contratação pelo site: os dados do contratante, o contrato gerado e a
    assinatura (eletrônica, aqui, ou gov.br, com o PDF assinado enviado). A
    pessoa acessa pelo `token` do link; assinado, vira solicitação."""

    __tablename__ = "contratos_digitais"

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    token: Mapped[str] = mapped_column(sa.String(64), unique=True)
    # Campos do contratante (os do contrato) e o endereço do site.
    dados: Mapped[dict] = mapped_column(sa.JSON)
    email: Mapped[str] = mapped_column(sa.String(200))
    # aguardando ou assinado.
    situacao: Mapped[str] = mapped_column(sa.String(20), default="aguardando", index=True)
    # eletronica ou govbr.
    metodo: Mapped[str] = mapped_column(sa.String(20), default="")
    assinado_em: Mapped[datetime | None] = mapped_column(sa.DateTime)
    assinatura_nome: Mapped[str] = mapped_column(sa.String(150), default="")
    ip: Mapped[str] = mapped_column(sa.String(64), default="")
    navegador: Mapped[str] = mapped_column(sa.String(300), default="")
    # SHA-256 do contrato aceito (eletrônica) ou do PDF assinado recebido (gov.br).
    hash_contrato: Mapped[str] = mapped_column(sa.String(64), default="")
    chave_assinado: Mapped[str] = mapped_column(sa.String(160), default="")
    # Logotipo enviado no formulário (plataforma/contratos/<id>/<ULID>); vazio se não enviou.
    logo_chave: Mapped[str] = mapped_column(sa.String(160), default="")
    logo_tipo: Mapped[str] = mapped_column(sa.String(20), default="")
    solicitacao_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("solicitacoes_implantacao.id", ondelete="SET NULL"), index=True
    )
    criado_em: Mapped[datetime] = mapped_column(sa.DateTime)
    atualizado_em: Mapped[datetime] = mapped_column(sa.DateTime)


# Corpo dos e-mails: no MySQL, TEXT para só 64 KB; MEDIUMTEXT vai a 16 MB.
TextoLongo = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


class EmailAssociacao(BaseCentral):
    """Mensagem da caixa de e-mail da associação: recebida (lida por IMAP) ou
    enviada pelo painel (SMTP). As recebidas guardam o UID para baixar os
    anexos do servidor de e-mail quando alguém abrir."""

    __tablename__ = "emails_associacao"
    __table_args__ = (sa.UniqueConstraint("pasta", "uidvalidity", "uid"),)

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    # entrada (recebida) ou enviado.
    pasta: Mapped[str] = mapped_column(sa.String(10), index=True)
    uid: Mapped[int | None] = mapped_column(sa.BigInteger)
    uidvalidity: Mapped[int | None] = mapped_column(sa.BigInteger)
    message_id: Mapped[str] = mapped_column(sa.String(300), default="")
    em_resposta_a: Mapped[str] = mapped_column(sa.String(300), default="")
    de_nome: Mapped[str] = mapped_column(sa.String(200), default="")
    de_email: Mapped[str] = mapped_column(sa.String(200), default="", index=True)
    para: Mapped[str] = mapped_column(sa.Text, default="")
    cc: Mapped[str] = mapped_column(sa.Text, default="")
    assunto: Mapped[str] = mapped_column(sa.String(500), default="")
    data: Mapped[datetime] = mapped_column(sa.DateTime, index=True)
    texto: Mapped[str] = mapped_column(TextoLongo, default="")
    html: Mapped[str] = mapped_column(TextoLongo, default="")
    # [{"nome", "tipo", "tamanho"}], na ordem do e-mail.
    anexos: Mapped[list] = mapped_column(sa.JSON, default=list)
    lido: Mapped[bool] = mapped_column(sa.Boolean, default=False, index=True)
    respondido_em: Mapped[datetime | None] = mapped_column(sa.DateTime)
    enviado_por_id: Mapped[str | None] = mapped_column(
        sa.ForeignKey("administradores.id", ondelete="SET NULL")
    )
    criado_em: Mapped[datetime] = mapped_column(sa.DateTime)

    enviado_por: Mapped["Administrador | None"] = relationship()

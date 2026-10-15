"""Enums do CRM — os valores são os nomes dos enums no front-end."""

from app.core.enums import EnumRotulado


class Finalidade(EnumRotulado):
    venda = "venda", "Venda"
    locacao = "locacao", "Locação"
    temporada = "temporada", "Temporada"


class TipoImovel(EnumRotulado):
    apartamento = "apartamento", "Apartamento"
    casa = "casa", "Casa"
    casaCondominio = "casaCondominio", "Casa de condomínio"
    cobertura = "cobertura", "Cobertura"
    kitnet = "kitnet", "Kitnet / Studio"
    flat = "flat", "Flat"
    sala = "sala", "Sala comercial"
    loja = "loja", "Loja"
    galpao = "galpao", "Galpão"
    predio = "predio", "Prédio comercial"
    terreno = "terreno", "Terreno / Lote"
    sitio = "sitio", "Sítio / Chácara"
    fazenda = "fazenda", "Fazenda"
    outro = "outro", "Outro"


class StatusImovel(EnumRotulado):
    disponivel = "disponivel", "Disponível"
    reservado = "reservado", "Reservado"
    alugado = "alugado", "Alugado"
    vendido = "vendido", "Vendido"
    inativo = "inativo", "Inativo"


class Mobiliado(EnumRotulado):
    nao = "nao", "Não mobiliado"
    semi = "semi", "Semimobiliado"
    sim = "sim", "Mobiliado"


class AnexoTipo(EnumRotulado):
    foto = "foto", "Foto"
    video = "video", "Vídeo"
    arquivo = "arquivo", "Arquivo"
    link = "link", "Link"


class TipoPessoa(EnumRotulado):
    fisica = "fisica", "Pessoa Física"
    juridica = "juridica", "Pessoa Jurídica"


class PapelContato(EnumRotulado):
    lead = "lead", "Lead / Interessado"
    comprador = "comprador", "Comprador"
    locatario = "locatario", "Locatário"
    proprietario = "proprietario", "Proprietário"
    fiador = "fiador", "Fiador"
    parceiro = "parceiro", "Parceiro / Corretor"
    fornecedor = "fornecedor", "Fornecedor"


class OrigemContato(EnumRotulado):
    site = "site", "Site"
    portal = "portal", "Portais imobiliários"
    indicacao = "indicacao", "Indicação"
    placa = "placa", "Placa / Faixada"
    instagram = "instagram", "Instagram"
    facebook = "facebook", "Facebook"
    whatsapp = "whatsapp", "WhatsApp"
    google = "google", "Google"
    evento = "evento", "Evento / Feira"
    outro = "outro", "Outro"


class EtapaFunil(EnumRotulado):
    novo = "novo", "Novo contato"
    contato = "contato", "Em contato"
    visita = "visita", "Visita agendada"
    proposta = "proposta", "Proposta"
    negociacao = "negociacao", "Negociação"
    fechado = "fechado", "Negócio fechado"
    perdido = "perdido", "Perdido"


class TipoEvento(EnumRotulado):
    anotacao = "anotacao", "Anotação"
    lembrete = "lembrete", "Lembrete"
    recado = "recado", "Recado"
    visita = "visita", "Visita"
    ligacao = "ligacao", "Ligação"
    reuniao = "reuniao", "Reunião"


class Prioridade(EnumRotulado):
    baixa = "baixa", "Baixa"
    normal = "normal", "Normal"
    alta = "alta", "Alta"

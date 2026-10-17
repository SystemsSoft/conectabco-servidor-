from datetime import datetime
from typing import Annotated

from pydantic import Field

from app.core.schemas import Esquema
from app.modules.site.enums import StatusLead, TipoLead


def Texto(n: int):  # noqa: N802
    return Annotated[str, Field(max_length=n)]


class ConfiguracaoSite(Esquema):
    """O que o site mostra e como os leads são atendidos. Contatos em branco
    usam os dados da imobiliária (Personalização)."""

    no_ar: bool = True

    # Conteúdo
    titulo: Texto(120) = "Encontre o imóvel ideal para você"
    subtitulo: Texto(300) = (
        "Compra, venda e locação com atendimento personalizado de quem "
        "conhece a região."
    )
    texto_sobre: Texto(3000) = (
        "Atuamos com ética, transparência e dedicação para que cada cliente "
        "encontre o imóvel certo — seja para morar, investir ou alugar. "
        "Cuidamos de toda a negociação, da primeira visita à entrega das chaves."
    )
    chamada_anuncie: Texto(300) = (
        "Quer vender ou alugar seu imóvel? Cadastre-o com a gente e receba "
        "uma avaliação sem compromisso."
    )
    mensagem_obrigado: Texto(300) = (
        "Recebemos sua mensagem! Um de nossos corretores vai falar com você "
        "em breve."
    )

    # Contatos e redes
    whatsapp: Texto(20) = ""
    telefone: Texto(40) = ""
    email: Texto(200) = ""
    endereco: Texto(300) = ""
    horario: Texto(120) = "Segunda a sexta, das 9h às 18h"
    instagram: Texto(200) = ""
    facebook: Texto(200) = ""

    # Funcionalidades
    mostrar_busca: bool = True
    mostrar_destaques: bool = True
    mostrar_sobre: bool = True
    mostrar_contato: bool = True
    mostrar_anuncie: bool = True
    permitir_agendar_visita: bool = True
    botao_whatsapp: bool = True
    mostrar_valores: bool = True
    mostrar_area_inquilino: bool = True

    # Atendimento dos leads
    distribuir_na_fila: bool = True
    criar_tarefa: bool = True

    # Buscadores (Google)
    meta_descricao: Texto(300) = ""


class LeadSaida(Esquema):
    id: str
    tipo: TipoLead
    status: StatusLead
    nome: str
    email: str
    telefone: str
    mensagem: str
    data_visita: datetime | None
    imovel_id: str | None
    contato_id: str | None
    corretor_id: str | None
    atendimento_id: str | None
    evento_id: str | None
    pagina: str
    observacao: str
    criado_em: datetime
    atualizado_em: datetime


class LeadAtualizacao(Esquema):
    """O que a equipe muda no lead (os dados do cliente vêm do site)."""

    status: StatusLead
    corretor_id: str | None = None
    observacao: Texto(5000) = ""


class LeadEntrada(Esquema):
    """Formulário do site."""

    tipo: TipoLead = TipoLead.contato
    nome: Texto(200)
    email: Texto(200) = ""
    telefone: Texto(30) = ""
    mensagem: Texto(3000) = ""
    imovel_codigo: Texto(20) = ""
    data_visita: datetime | None = None
    consentimento: bool = False
    pagina: Texto(300) = ""

from app.core.enums import EnumRotulado


class PerfilAcesso(EnumRotulado):
    administrador = "administrador", "Administrador"
    gerente = "gerente", "Gerente"
    corretor = "corretor", "Corretor"
    financeiro = "financeiro", "Financeiro"
    atendente = "atendente", "Atendente"


class ModuloSistema(EnumRotulado):
    cadastrosCrm = "cadastrosCrm", "Cadastros e CRM"
    locacao = "locacao", "Administração de Locação"
    vendas = "vendas", "Administração de Vendas"
    financeiro = "financeiro", "Financeiro"
    fiscal = "fiscal", "Fiscal"
    contratosRelatorios = "contratosRelatorios", "Contratos e Relatórios"
    equipeSeguranca = "equipeSeguranca", "Equipe e Segurança"
    personalizacao = "personalizacao", "Personalização"


class AcaoPermissao(EnumRotulado):
    visualizar = "visualizar", "Ver"
    criar = "criar", "Criar"
    editar = "editar", "Editar"
    excluir = "excluir", "Excluir"


class PermissaoEspecial(EnumRotulado):
    verValoresFinanceiros = "verValoresFinanceiros", "Ver valores financeiros"
    exportarDados = "exportarDados", "Exportar e imprimir dados"
    verComissoesDeTodos = "verComissoesDeTodos", "Ver comissões de todos"
    gerenciarUsuarios = "gerenciarUsuarios", "Gerenciar usuários"


class TipoAtividade(EnumRotulado):
    login = "login", "Entrada no sistema"
    logout = "logout", "Saída do sistema"
    criacao = "criacao", "Criação"
    edicao = "edicao", "Edição"
    exclusao = "exclusao", "Exclusão"
    permissao = "permissao", "Permissões"
    atendimento = "atendimento", "Atendimento"
    comissao = "comissao", "Comissão"
    chat = "chat", "Chat"


class StatusFila(EnumRotulado):
    disponivel = "disponivel", "Disponível"
    emAtendimento = "emAtendimento", "Em atendimento"
    ausente = "ausente", "Ausente"


class OrigemAtendimento(EnumRotulado):
    plantao = "plantao", "Plantão"
    telefone = "telefone", "Telefone"
    whatsapp = "whatsapp", "WhatsApp"
    portal = "portal", "Portal imobiliário"
    site = "site", "Site"
    indicacao = "indicacao", "Indicação"


class TipoComissao(EnumRotulado):
    venda = "venda", "Venda"
    locacao = "locacao", "Locação"
    captacao = "captacao", "Captação"
    bonus = "bonus", "Bônus"
    ajuste = "ajuste", "Ajuste"


class StatusComissao(EnumRotulado):
    pendente = "pendente", "A aprovar"
    aprovada = "aprovada", "A pagar"
    paga = "paga", "Paga"
    cancelada = "cancelada", "Cancelada"


def permissoes_do_perfil(perfil: PerfilAcesso) -> dict:
    """Mesmas permissões sugeridas pelo app para cada perfil."""
    todas = [a.value for a in AcaoPermissao]
    leitura = ["visualizar"]
    operar = ["visualizar", "criar", "editar"]
    m = ModuloSistema
    match perfil:
        case PerfilAcesso.administrador:
            return {"modulos": {x.value: todas for x in m},
                    "especiais": [e.value for e in PermissaoEspecial]}  # fmt: skip
        case PerfilAcesso.gerente:
            return {
                "modulos": {
                    x.value: leitura if x == m.equipeSeguranca else todas for x in m
                },
                "especiais": ["verValoresFinanceiros", "exportarDados", "verComissoesDeTodos"],
            }
        case PerfilAcesso.corretor:
            return {"modulos": {"cadastrosCrm": operar, "vendas": operar,
                                "locacao": operar, "contratosRelatorios": leitura},
                    "especiais": []}  # fmt: skip
        case PerfilAcesso.financeiro:
            return {"modulos": {"financeiro": todas, "fiscal": todas, "vendas": leitura,
                                "locacao": leitura, "cadastrosCrm": leitura},
                    "especiais": ["verValoresFinanceiros", "exportarDados"]}  # fmt: skip
        case PerfilAcesso.atendente:
            return {"modulos": {"cadastrosCrm": operar, "locacao": leitura},
                    "especiais": []}  # fmt: skip

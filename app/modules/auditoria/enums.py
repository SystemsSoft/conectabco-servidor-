from app.core.enums import EnumRotulado


class TipoAuditoria(EnumRotulado):
    periodica = "periodica", "Periódica"
    entrada = "entrada", "Entrada do inquilino"
    saida = "saida", "Saída do inquilino"
    extraordinaria = "extraordinaria", "Extraordinária"


class StatusAuditoria(EnumRotulado):
    agendada = "agendada", "Agendada"
    emAndamento = "emAndamento", "Em andamento"
    concluida = "concluida", "Concluída"
    cancelada = "cancelada", "Cancelada"


class EstadoItem(EnumRotulado):
    pendente = "pendente", "Não avaliado"
    ok = "ok", "OK"
    atencao = "atencao", "Atenção"
    problema = "problema", "Problema"
    naoAplica = "naoAplica", "Não se aplica"


class TipoMidia(EnumRotulado):
    foto = "foto", "Foto"
    video = "video", "Vídeo"


class StatusTranscricao(EnumRotulado):
    naoSolicitada = "naoSolicitada", "Não solicitada"
    pendente = "pendente", "Na fila"
    processando = "processando", "Transcrevendo"
    concluida = "concluida", "Transcrita"
    erro = "erro", "Erro"


class Gravidade(EnumRotulado):
    critica = "critica", "Crítica"
    atencao = "atencao", "Atenção"
    info = "info", "Informativa"


class AreaPendencia(EnumRotulado):
    financeiro = "financeiro", "Financeiro"
    contrato = "contrato", "Contrato"
    imovel = "imovel", "Imóvel"
    documentos = "documentos", "Documentos"
    cadastro = "cadastro", "Cadastro"

from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import Field

from app.core.schemas import Esquema


def Texto(n: int):  # noqa: N802
    return Annotated[str, Field(max_length=n)]


class Configuracao(Esquema):
    ambiente: Literal["sandbox", "producao"] = "sandbox"
    client_id: Texto(200) = ""
    numero_cliente: Texto(20) = Field("", description="Código do beneficiário (cooperado)")
    codigo_modalidade: Annotated[int, Field(ge=1, le=99)] = 1
    numero_conta_corrente: Texto(20) = ""
    chave_pix: Texto(100) = ""
    conta_bancaria_id: str | None = Field(None, description="Conta do Financeiro que recebe o extrato")
    link_internet_banking: Annotated[str, Field(max_length=300, pattern=r"^https://")] = (
        "https://ib.sicoob.com.br/sicoobnet/ib/#/login"
    )


class ConfiguracaoEntrada(Configuracao):
    token: Texto(4000) | None = Field(None, description="Token do Sandbox; vazio mantém o atual")


class ConfiguracaoSaida(Configuracao):
    token_configurado: bool = False


class ResultadoTeste(Esquema):
    api: str
    nome: str
    ok: bool
    status_http: int | None
    mensagem: str


class Pagador(Esquema):
    documento: Texto(20)
    nome: Texto(200)
    endereco: Texto(200) = ""
    bairro: Texto(100) = ""
    cidade: Texto(100) = ""
    cep: Texto(9) = ""
    uf: Texto(2) = ""
    email: Texto(200) = ""


class BoletoEntrada(Esquema):
    seu_numero: Texto(18) = ""
    valor: Annotated[float, Field(gt=0)]
    vencimento: date
    pagador: Pagador
    multa_percentual: Annotated[float, Field(ge=0, le=100)] = 0
    juros_mes_percentual: Annotated[float, Field(ge=0, le=100)] = 0
    mensagem: Texto(80) = ""
    com_pix: bool = True
    cobranca_id: str | None = None


class BoletoSaida(Esquema):
    id: str
    ambiente: str
    nosso_numero: str
    seu_numero: str
    valor: float
    vencimento: date
    pagador_nome: str
    pagador_documento: str
    linha_digitavel: str
    codigo_barras: str
    situacao: str
    cobranca_id: str | None
    criado_em: datetime


class PixEntrada(Esquema):
    valor: Annotated[float, Field(gt=0)]
    devedor_documento: Texto(20) = ""
    devedor_nome: Texto(200) = ""
    descricao: Texto(140) = ""
    expiracao_horas: Annotated[int, Field(ge=1, le=720)] = 24
    cobranca_id: str | None = None


class PixSaida(Esquema):
    id: str
    ambiente: str
    txid: str
    valor: float
    devedor_nome: str
    devedor_documento: str
    descricao: str
    status: str
    copia_e_cola: str
    location: str
    cobranca_id: str | None
    criado_em: datetime
    qr_code_png: str = Field("", description="QR code do copia e cola (data URI)")


class PixRecebido(Esquema):
    end_to_end_id: str
    txid: str
    valor: float
    horario: str
    pagador: str
    info: str


class Saldo(Esquema):
    saldo: float
    saldo_limite: float
    saldo_bloqueado: float


class Transacao(Esquema):
    tipo: str
    valor: float
    data: date
    descricao: str
    documento: str
    complemento: str


class Extrato(Esquema):
    saldo_anterior: float
    saldo_atual: float
    transacoes: list[Transacao]


class ImportacaoExtrato(Esquema):
    mes: Annotated[int, Field(ge=1, le=12)]
    ano: Annotated[int, Field(ge=2000, le=2100)]


class ResultadoImportacao(Esquema):
    importadas: int
    repetidas: int


class Chamada(Esquema):
    id: str
    criado_em: datetime
    ambiente: str
    api: str
    operacao: str
    metodo: str
    caminho: str
    status_http: int | None
    duracao_ms: int
    sucesso: bool
    erro: str


class ChamadaDetalhe(Chamada):
    requisicao: str
    resposta: str


class Rascunho(Esquema):
    """Dados para preencher o formulário a partir de uma cobrança do aluguel."""

    valor: float
    vencimento: date
    pagador: Pagador
    descricao: str
    multa_percentual: float
    juros_mes_percentual: float


class CobrancaAberta(Esquema):
    id: str
    descricao: str
    locatario: str
    valor: float
    vencimento: date


class RetornoEntrada(Esquema):
    """Conteúdo do arquivo CNAB 240 de retorno, em base64."""

    conteudo: str
    aplicar: bool = False


class ItemRetorno(Esquema):
    linha: int
    nosso_numero: str
    seu_numero: str
    movimento: str
    valor_pago: float
    data_credito: date | None
    # baixar | aplicada | ja_paga | divergente | sem_boleto | sem_cobranca | ignorado
    situacao: str
    mensagem: str
    cobranca_id: str | None = None
    descricao: str = ""
    locatario: str = ""


class ResultadoRetorno(Esquema):
    arquivo_linhas: int
    aplicado: bool
    itens: list[ItemRetorno]
    baixas: int

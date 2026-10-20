"""Leitura do arquivo de retorno de cobrança (CNAB 240, layout FEBRABAN usado
pelo Sicoob). Só interpreta o texto; não toca no banco."""

from dataclasses import dataclass
from datetime import date

from app.core.errors import RegraNegocio

# Códigos de movimento (posições 16-17 do segmento T) que significam dinheiro recebido.
LIQUIDACAO = {"06": "Liquidação", "17": "Liquidação após baixa"}
OUTROS = {
    "02": "Entrada confirmada", "03": "Entrada rejeitada", "09": "Baixa",
    "10": "Baixa por solicitação", "14": "Alteração de vencimento", "23": "Encaminhado a protesto",
}  # fmt: skip


@dataclass
class Pagamento:
    linha: int
    movimento: str
    nosso_numero: str  # só dígitos, sem zeros à esquerda
    seu_numero: str
    vencimento: date | None
    valor_titulo: float
    valor_pago: float = 0.0
    data_credito: date | None = None
    data_ocorrencia: date | None = None


@dataclass
class ArquivoRetorno:
    banco: str
    cedente: str
    linhas: int
    pagamentos: list[Pagamento]


def _texto(raw: bytes | str) -> str:
    if isinstance(raw, str):
        return raw
    for cod in ("utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(cod)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", "replace")


def _data(v: str) -> date | None:
    v = v.strip()
    if len(v) != 8 or not v.isdigit() or v == "00000000":
        return None
    try:
        return date(int(v[4:]), int(v[2:4]), int(v[:2]))
    except ValueError:
        return None


def _valor(v: str) -> float:
    v = v.strip()
    return int(v) / 100 if v.isdigit() else 0.0


def _campo(linha: str, ini: int, fim: int) -> str:
    """Posições FEBRABAN, contadas de 1 e inclusivas."""
    return linha[ini - 1 : fim]


def ler(raw: bytes | str) -> ArquivoRetorno:
    linhas = [x.rstrip("\r\n") for x in _texto(raw).replace("\x00", "").split("\n")]
    linhas = [x for x in linhas if x.strip()]
    if not linhas:
        raise RegraNegocio("O arquivo está vazio.")
    if any(len(x) == 400 for x in linhas[:3]):
        raise RegraNegocio("Este é um arquivo CNAB 400. Peça ao Sicoob o retorno no layout CNAB 240.")
    if len(linhas[0]) != 240:
        raise RegraNegocio("Arquivo inválido: o retorno CNAB 240 tem 240 posições por linha.")
    cab = linhas[0]
    if _campo(cab, 8, 8) != "0":
        raise RegraNegocio("Arquivo inválido: falta o cabeçalho do arquivo.")
    banco = _campo(cab, 1, 3)
    if banco != "756":
        raise RegraNegocio(f"O arquivo é do banco {banco}; só o retorno do Sicoob (756) é aceito.")

    pagamentos: dict[int, Pagamento] = {}
    atual: Pagamento | None = None
    for n, ln in enumerate(linhas, 1):
        if len(ln) != 240 or _campo(ln, 8, 8) != "3":
            continue
        segmento = _campo(ln, 14, 14)
        if segmento == "T":
            nosso = _campo(ln, 38, 57).strip().lstrip("0")
            atual = Pagamento(
                linha=n, movimento=_campo(ln, 16, 17), nosso_numero="".join(c for c in nosso if c.isdigit()),
                seu_numero=_campo(ln, 59, 73).strip(), vencimento=_data(_campo(ln, 74, 81)),
                valor_titulo=_valor(_campo(ln, 82, 96)),
            )  # fmt: skip
            pagamentos[n] = atual
        elif segmento == "U" and atual is not None:
            atual.valor_pago = _valor(_campo(ln, 78, 92))
            atual.data_ocorrencia = _data(_campo(ln, 138, 145))
            atual.data_credito = _data(_campo(ln, 146, 153)) or atual.data_ocorrencia
            atual = None
    return ArquivoRetorno(
        banco=banco, cedente=_campo(cab, 73, 102).strip(), linhas=len(linhas), pagamentos=list(pagamentos.values())
    )

"""Contrato de prestação de serviços em PDF: o modelo original da associação
(contrato/modelo.pdf) com o quadro do CONTRATANTE (página 1) e a data
(última página) preenchidos por cima. Na assinatura eletrônica, ganha uma
página final com o registro da assinatura."""

import hashlib
import io
from datetime import date, datetime
from pathlib import Path

from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

MODELO = Path(__file__).parent / "contrato" / "modelo.pdf"
FONTE, TAMANHO = "Helvetica", 7.5
MESES = ("janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro")  # fmt: skip

# Células do quadro na página 1: campo -> (x inicial, x final, topo da linha), em pontos a partir
# do canto superior esquerdo (medidas do modelo).
_CELULAS = {
    "nome": (156, 579, 161.7),
    "endereco": (156, 374, 174.3), "numero": (465, 579, 174.3),
    "bairro": (156, 235, 187.1), "cidade": (381, 458, 187.1), "uf": (550, 579, 187.1),
    "cpf": (156, 235, 199.7), "identidade": (381, 579, 199.7),
    "cnpj": (156, 235, 212.3), "creci_pj": (381, 579, 212.3),
    "creci": (156, 235, 224.9), "nome_comercial": (381, 579, 224.9),
    "telefone_1": (395, 458, 237.7), "telefone_2": (480, 579, 237.7),
    "site": (156, 374, 262.5), "servidor": (465, 579, 262.5),
    "instagram": (165, 300, 275.1), "facebook": (443, 579, 275.1),
    "tiktok": (165, 300, 287.7), "youtube": (443, 579, 287.7),
    "dns": (156, 220, 300.5), "data_implantacao": (381, 458, 300.5), "horario_implantacao": (530, 579, 300.5),
}  # fmt: skip
_ENDERECO_COMERCIAL = (156, 235, 237.7, 22)  # duas linhas de altura
_DATA_FINAL = (48, 271.9)  # depois de "Data", na última página


def _formatar_documento(d: str) -> str:
    if len(d) == 11 and d.isdigit():
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    if len(d) == 14 and d.isdigit():
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    return d


def _data_por_extenso(d: date) -> str:
    return f"{d.day} de {MESES[d.month - 1]} de {d.year}"


def _cabe(texto: str, largura: float, tamanho: float = TAMANHO) -> tuple[str, float]:
    """Reduz a fonte (até 5,5) e, se ainda não couber, corta com reticências."""
    from reportlab.pdfbase.pdfmetrics import stringWidth

    while tamanho > 5.5 and stringWidth(texto, FONTE, tamanho) > largura:
        tamanho -= 0.5
    while texto and stringWidth(texto, FONTE, tamanho) > largura:
        texto = texto[:-2] + "…"
    return texto, tamanho


def _sobreposicao(largura: float, altura: float, desenhar) -> PdfReader:
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=(largura, altura))
    desenhar(c, altura)
    c.save()
    buffer.seek(0)
    return PdfReader(buffer)


def gerar(dados: dict[str, str], data_contrato: date) -> bytes:
    """O contrato preenchido. `dados` usa os nomes de campo do contratante
    (nome, endereco, ..., site); datas como texto ISO."""
    valores = dict(dados)
    valores["cpf"] = _formatar_documento(valores.get("cpf", ""))
    valores["cnpj"] = _formatar_documento(valores.get("cnpj", ""))
    if v := valores.get("data_implantacao"):
        valores["data_implantacao"] = date.fromisoformat(v).strftime("%d/%m/%Y")

    escritor = PdfWriter(clone_from=str(MODELO))
    ultima = len(escritor.pages) - 1
    for indice, pagina in enumerate(escritor.pages):
        largura, altura = float(pagina.mediabox.width), float(pagina.mediabox.height)
        if indice == 0:
            def desenhar(c, h):
                c.setFont(FONTE, TAMANHO)
                for campo, (x0, x1, topo) in _CELULAS.items():
                    if texto := (valores.get(campo) or "").strip():
                        texto, tamanho = _cabe(texto, x1 - x0)
                        c.setFont(FONTE, tamanho)
                        c.drawString(x0, h - topo - 7.6, texto)
                if texto := (valores.get("endereco_comercial") or "").strip():
                    x0, x1, topo, alto = _ENDERECO_COMERCIAL
                    linhas = simpleSplit(texto, FONTE, 6, x1 - x0)[:3]
                    c.setFont(FONTE, 6)
                    for i, linha in enumerate(linhas):
                        c.drawString(x0, h - topo - 6 - i * 7, linha)

            pagina.merge_page(_sobreposicao(largura, altura, desenhar).pages[0])
        elif indice == ultima:
            def desenhar(c, h):
                c.setFont(FONTE, 10)
                c.drawString(_DATA_FINAL[0], h - _DATA_FINAL[1] - 8, _data_por_extenso(data_contrato))

            pagina.merge_page(_sobreposicao(largura, altura, desenhar).pages[0])
    escritor.add_metadata({"/Title": "Contrato de prestação de serviços - Associação Conecta do Brasil",
                           "/Author": "Associação Conecta do Brasil"})  # fmt: skip
    saida = io.BytesIO()
    escritor.write(saida)
    return saida.getvalue()


def sha256(conteudo: bytes) -> str:
    return hashlib.sha256(conteudo).hexdigest()


def com_registro_de_assinatura(contrato: bytes, registro: dict[str, str]) -> bytes:
    """O contrato com uma página final de registro da assinatura eletrônica
    (quem, quando, de onde e o hash do contrato assinado)."""
    escritor = PdfWriter(clone_from=io.BytesIO(contrato))
    largura, altura = float(escritor.pages[0].mediabox.width), float(escritor.pages[0].mediabox.height)

    def desenhar(c, h):
        y = h - 70
        c.setFont("Helvetica-Bold", 14)
        c.drawString(50, y, "Registro de assinatura eletrônica")
        y -= 22
        c.setFont("Helvetica", 9.5)
        for linha in simpleSplit(
            "O CONTRATANTE abaixo identificado leu e aceitou eletronicamente o Contrato de Prestação de "
            "Serviços das páginas anteriores, por meio da área de contratação da Associação Conecta do "
            "Brasil, conforme a cláusula 15.5 (assinatura eletrônica admitida).", "Helvetica", 9.5, largura - 100,
        ):  # fmt: skip
            c.drawString(50, y, linha)
            y -= 13
        y -= 10
        for rotulo, valor in registro.items():
            c.setFont("Helvetica-Bold", 9.5)
            c.drawString(50, y, rotulo)
            c.setFont("Helvetica", 9.5)
            for i, linha in enumerate(simpleSplit(valor, "Helvetica", 9.5, largura - 230)):
                c.drawString(200, y - i * 12, linha)
            y -= 12 * max(1, len(simpleSplit(valor, "Helvetica", 9.5, largura - 230))) + 6
        c.setFont("Helvetica", 8)
        c.drawString(50, 40, f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} · Associação Conecta do Brasil")

    escritor.add_page(_sobreposicao(largura, altura, desenhar).pages[0])
    saida = io.BytesIO()
    escritor.write(saida)
    return saida.getvalue()

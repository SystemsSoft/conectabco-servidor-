"""Formatação em pt-BR usada em textos devolvidos pela API."""


def formatar_moeda(valor: float | None) -> str:
    if valor is None:
        return "—"
    texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


def decimal_para_texto(valor: float | None) -> str:
    if valor is None:
        return ""
    texto = str(int(valor)) if valor == int(valor) else str(valor)
    return texto.replace(".", ",")

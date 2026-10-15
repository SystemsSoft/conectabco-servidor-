"""Validação de CPF e CNPJ pelos dígitos verificadores."""

import re


def _digitos(valor: str) -> str:
    return re.sub(r"\D", "", valor or "")


def _dv(base: str, pesos: list[int]) -> int:
    resto = sum(int(d) * p for d, p in zip(base, pesos)) % 11
    return 0 if resto < 2 else 11 - resto


def validar_cpf(valor: str) -> bool:
    d = _digitos(valor)
    if len(d) != 11 or d == d[0] * 11:
        return False
    d1 = _dv(d[:9], list(range(10, 1, -1)))
    d2 = _dv(d[:10], list(range(11, 1, -1)))
    return d[9:] == f"{d1}{d2}"


def validar_cnpj(valor: str) -> bool:
    d = _digitos(valor)
    if len(d) != 14 or d == d[0] * 14:
        return False
    pesos = [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]
    d1 = _dv(d[:12], pesos)
    d2 = _dv(d[:13], [6, *pesos])
    return d[12:] == f"{d1}{d2}"


def validar_cpf_cnpj(valor: str) -> bool:
    return validar_cpf(valor) if len(_digitos(valor)) == 11 else validar_cnpj(valor)

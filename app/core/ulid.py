"""ULID: identificador único de 26 caracteres que começa pelo instante da
criação (48 bits, ms) seguido de 80 bits aleatórios, em base32 de Crockford.
Ordena por data e não repete — usado nas chaves dos arquivos no S3."""

import re
import secrets
import time

_ALFABETO = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_FORMATO = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")


def novo_ulid() -> str:
    valor = (time.time_ns() // 1_000_000) << 80 | secrets.randbits(80)
    letras = []
    for _ in range(26):
        valor, resto = divmod(valor, 32)
        letras.append(_ALFABETO[resto])
    return "".join(reversed(letras))


def ulid_valido(texto: str) -> bool:
    return bool(_FORMATO.match(texto or ""))

"""Enums com rótulo em português; o valor é o mesmo nome usado no Dart."""

from enum import StrEnum

import sqlalchemy as sa


class EnumRotulado(StrEnum):
    rotulo: str

    def __new__(cls, valor: str, rotulo: str):
        obj = str.__new__(cls, valor)
        obj._value_ = valor
        obj.rotulo = rotulo
        return obj

    @classmethod
    def opcoes(cls) -> list[dict[str, str]]:
        return [{"valor": e.value, "rotulo": e.rotulo} for e in cls]


def coluna_enum(enum: type[EnumRotulado]) -> sa.Enum:
    """Enum gravado como VARCHAR com o valor (portável, sem ENUM nativo)."""
    return sa.Enum(
        enum,
        native_enum=False,
        length=max(len(e.value) for e in enum) + 10,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )

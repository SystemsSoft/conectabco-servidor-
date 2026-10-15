"""Base dos schemas da API: JSON em camelCase, igual ao front-end (Dart)."""

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class Esquema(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


class Pagina[T](Esquema):
    itens: list[T]
    total: int
    limite: int
    deslocamento: int


class Opcao(Esquema):
    """Valor de enum e o rótulo exibido na interface."""

    valor: str
    rotulo: str


def pagina[T](itens: list[T], total: int, limite: int, deslocamento: int) -> Pagina[T]:
    return Pagina[T](itens=itens, total=total, limite=limite, deslocamento=deslocamento)

"""Erros de negócio e a resposta HTTP de cada um ({"detail": "..."})."""

import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class RegraNegocio(Exception):
    """Violação de regra de negócio (HTTP 422)."""

    status_code = 422

    def __init__(self, mensagem: str):
        super().__init__(mensagem)
        self.mensagem = mensagem


class NaoEncontrado(RegraNegocio):
    """Registro inexistente (HTTP 404)."""

    status_code = 404


def validar_id(id: str) -> str:
    """Ids são UUIDs gerados pelo app (permite criar com PUT, sem duplicar)."""
    try:
        return str(uuid.UUID(id))
    except ValueError:
        raise RegraNegocio("Identificador inválido.") from None


def _campo(loc: tuple) -> str:
    partes = [str(p) for p in loc if p not in ("body", "query", "path")]
    return ".".join(partes) or "requisição"


def registrar_tratadores(app: FastAPI) -> None:
    @app.exception_handler(RegraNegocio)
    async def _regra(_: Request, exc: RegraNegocio) -> JSONResponse:
        return JSONResponse({"detail": exc.mensagem}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validacao(_: Request, exc: RequestValidationError) -> JSONResponse:
        erros = [
            {"campo": _campo(e.get("loc", ())), "mensagem": e.get("msg", "")}
            for e in exc.errors()
        ]
        primeiro = erros[0] if erros else {"campo": "", "mensagem": ""}
        return JSONResponse(
            {
                "detail": f"Campo inválido: {primeiro['campo']} ({primeiro['mensagem']})",
                "erros": erros,
            },
            status_code=422,
        )

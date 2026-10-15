"""Erros de negócio e a resposta HTTP de cada um ({"detail": "..."})."""

from fastapi import FastAPI, Request
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


def registrar_tratadores(app: FastAPI) -> None:
    @app.exception_handler(RegraNegocio)
    async def _regra(_: Request, exc: RegraNegocio) -> JSONResponse:
        return JSONResponse({"detail": exc.mensagem}, status_code=exc.status_code)

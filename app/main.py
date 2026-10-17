"""Criação da aplicação FastAPI."""

import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings
from app.core.database import get_engine
from app.core.errors import registrar_tratadores
from app.modules import carregar_models, roteadores

PREFIXO_API = "/api/v1"


def create_app() -> FastAPI:
    s = get_settings()
    carregar_models()
    app = FastAPI(
        title=s.app_nome,
        version=s.versao,
        description="API do Sistema de Gestão Imobiliária – Marcelo Bonifácio, "
        "Corretor de Imóveis (CRECI 065655 RJ).",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.lista_cors,
        # Flutter web em desenvolvimento (qualquer porta local).
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_methods=["*"],
        allow_headers=["*"],
    )
    registrar_tratadores(app)
    for router, dependencias in roteadores():
        app.include_router(router, prefix=PREFIXO_API, dependencies=dependencias)

    # Site público (/, /imoveis, /imovel/{codigo}...), sem login.
    from app.modules.site.publico import PASTA, router as site_publico

    app.include_router(site_publico)
    from app.modules.inquilino.portal import router as portal_inquilino

    app.include_router(portal_inquilino)
    app.mount("/estatico", StaticFiles(directory=PASTA / "static"), name="estatico")

    @app.get("/saude", tags=["Sistema"])
    def saude() -> dict:
        return {"status": "ok", "versao": s.versao}

    @app.get("/saude/banco", tags=["Sistema"])
    def saude_banco():
        if not get_settings().banco_configurado:
            return JSONResponse(
                {"status": "erro", "detail": "Banco não configurado (.env)."}, 503
            )
        try:
            with get_engine().connect() as c:
                versao = c.scalar(sa.text("SELECT VERSION()"))
            return {"status": "ok", "versao": versao}
        except Exception as e:  # noqa: BLE001 - diagnóstico da conexão
            return JSONResponse({"status": "erro", "detail": str(e)}, 503)

    return app


app = create_app()

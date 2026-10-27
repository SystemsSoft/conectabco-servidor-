"""Criação da aplicação FastAPI."""

import sqlalchemy as sa
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.core import imobiliarias
from app.core.config import get_settings
from app.core.database import motor, motor_central
from app.core.errors import registrar_tratadores
from app.modules import carregar_models, roteadores

PREFIXO_API = "/api/v1"


def create_app() -> FastAPI:
    s = get_settings()
    carregar_models()
    app = FastAPI(
        title=s.app_nome,
        version=s.versao,
        description="API do Sistema de Gestão Imobiliária. Atende várias "
        "imobiliárias, cada uma com o seu banco: informe qual no cabeçalho "
        "X-Imobiliaria (ou acesse pelo domínio dela).",
    )
    app.add_middleware(imobiliarias.IdentificarImobiliaria)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=s.lista_cors,
        # Flutter web em desenvolvimento (qualquer porta local).
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
        allow_methods=["*"],
        allow_headers=["*"],
    )
    registrar_tratadores(app)
    documentar = Depends(imobiliarias.cabecalho)
    for router, dependencias in roteadores():
        app.include_router(router, prefix=PREFIXO_API, dependencies=[documentar, *dependencias])

    # Site público (/, /imoveis, /imovel/{codigo}...), sem login.
    from app.modules.site.publico import PASTA, router as site_publico

    app.include_router(site_publico)
    from app.modules.inquilino.portal import router as portal_inquilino

    app.include_router(portal_inquilino)
    from app.modules.auditoria.relatorio import router as relatorio_auditoria
    from app.modules.proprietario.portal import router as portal_proprietario

    app.include_router(portal_proprietario)
    app.include_router(relatorio_auditoria)
    app.mount("/estatico", StaticFiles(directory=PASTA / "static"), name="estatico")
    # Painel da plataforma: cadastro das imobiliárias.
    from app.central.painel import router as painel

    app.include_router(painel)
    # Área do representante: envia corretores para implantação.
    from app.central.area_representante import router as area_representante

    app.include_router(area_representante)
    # Pré-cadastro do site institucional: vira lead do Comercial.
    from app.central.pre_cadastro import router as pre_cadastro

    app.include_router(pre_cadastro)
    # App de gestão (Flutter web), em todos os domínios.
    from app.core.app_gestao import router as app_gestao

    app.include_router(app_gestao)

    @app.get("/saude", tags=["Sistema"])
    def saude() -> dict:
        return {"status": "ok", "versao": s.versao}

    @app.get("/saude/banco", tags=["Sistema"])
    def saude_banco():
        """Banco central e, se a requisição identificar a imobiliária, o dela."""
        if not get_settings().banco_configurado:
            return JSONResponse(
                {"status": "erro", "detail": "Banco não configurado (.env)."}, 503
            )
        try:
            resposta = {"status": "ok", "central": _versao(motor_central())}
            if imob := imobiliarias.identificada():
                resposta |= {"imobiliaria": imob.slug, "banco": _versao(motor(imob))}
            return resposta
        except Exception as e:  # noqa: BLE001 - diagnóstico da conexão
            return JSONResponse({"status": "erro", "detail": str(e)}, 503)

    return app


def _versao(engine: sa.Engine) -> str:
    with engine.connect() as c:
        c.execute(sa.text("SELECT 1"))
        return ".".join(map(str, c.dialect.server_version_info or ()))


app = create_app()

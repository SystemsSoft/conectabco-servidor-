"""Imobiliárias atendidas pelo servidor.

Todas usam o mesmo código (as mesmas regras de negócio), mas cada uma tem o
seu banco de dados, a sua pasta de arquivos e a sua chave de assinatura dos
tokens e links. O cadastro fica no banco central (app/central), mantido pelo
`python gerenciar.py imobiliaria ...`.

A imobiliária de cada requisição é identificada, nesta ordem, por:
  1. cabeçalho X-Imobiliaria (app de gestão);
  2. parâmetro ?imob= (links assinados, que o navegador abre sem cabeçalho);
  3. domínio acessado (site público e portais do inquilino e do proprietário);
  4. IMOBILIARIA_PADRAO do .env, se houver.
Ela fica num ContextVar durante a requisição (ou a tarefa do gerenciar.py,
com `usar`), de onde get_db, os arquivos e as assinaturas a leem."""

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

import anyio
from fastapi import Header, Request
from starlette.datastructures import Headers, QueryParams
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import get_settings
from app.core.errors import RegraNegocio

log = logging.getLogger("imobiliarias")

CABECALHO = "X-Imobiliaria"
PARAMETRO = "imob"
# Segundos até reler o cadastro (imobiliárias e domínios novos).
VALIDADE_CADASTRO = 30


@dataclass(frozen=True)
class Imobiliaria:
    slug: str
    nome: str
    banco: str
    site_url: str = ""
    dominios: tuple[str, ...] = ()
    ativa: bool = True
    cor_primaria: str = ""
    cor_destaque: str = ""
    # ULID fixo e único: prefixo de todos os arquivos dela no armazenamento.
    chave: str = ""

    @property
    def pasta_arquivos(self) -> Path:
        """Pasta dos arquivos de antes do S3 (gerenciar.py migrar-arquivos)."""
        return Path(get_settings().arquivos_dir) / self.slug


class ImobiliariaNaoIdentificada(RegraNegocio):
    status_code = 400

    def __init__(self):
        super().__init__(
            "Imobiliária não identificada: informe o cabeçalho X-Imobiliaria "
            "ou acesse pelo domínio dela."
        )


class _NaoEncontrada(Exception):
    pass


_atual: ContextVar[Imobiliaria | None] = ContextVar("imobiliaria", default=None)
# Como a requisição disse qual é: cabecalho, parametro, dominio ou padrao.
_origem: ContextVar[str] = ContextVar("origem_imobiliaria", default="")


def atual() -> Imobiliaria:
    imob = _atual.get()
    if imob is None:
        raise ImobiliariaNaoIdentificada()
    return imob


def identificada() -> Imobiliaria | None:
    """A imobiliária atual, se a requisição identificou alguma."""
    return _atual.get()


def origem() -> str:
    """Como a imobiliária foi identificada: cabecalho, parametro, dominio ou
    padrao (IMOBILIARIA_PADRAO)."""
    return _origem.get()


@contextmanager
def usar(imob: Imobiliaria) -> Iterator[Imobiliaria]:
    """Define a imobiliária atual (tarefas fora de uma requisição)."""
    token = _atual.set(imob)
    try:
        yield imob
    finally:
        _atual.reset(token)


# ------------------------------------------------- Cadastro em memória


@dataclass
class _Cadastro:
    expira: float
    por_slug: dict[str, Imobiliaria] = field(default_factory=dict)
    por_dominio: dict[str, Imobiliaria] = field(default_factory=dict)


_cadastro: _Cadastro | None = None


def _vencido() -> bool:
    return _cadastro is None or _cadastro.expira < time.monotonic()


def _cadastro_atual() -> _Cadastro:
    """Relido do banco central a cada VALIDADE_CADASTRO segundos; se ele
    estiver fora do ar, segue com a última leitura."""
    global _cadastro
    if _vencido():
        from app.central.services import carregar

        try:
            lista = carregar()
        except Exception:
            if _cadastro is None:
                raise
            log.exception("Banco central indisponível: usando o cadastro anterior.")
            _cadastro.expira = time.monotonic() + VALIDADE_CADASTRO
            return _cadastro
        _cadastro = _Cadastro(
            time.monotonic() + VALIDADE_CADASTRO,
            {i.slug: i for i in lista},
            {d: i for i in lista for d in i.dominios},
        )
    return _cadastro


def limpar_cadastro() -> None:
    """Força reler o cadastro na próxima consulta."""
    global _cadastro
    _cadastro = None


def buscar(slug: str) -> Imobiliaria | None:
    return _cadastro_atual().por_slug.get(slug.strip().lower())


def todas(somente_ativas: bool = True) -> list[Imobiliaria]:
    lista = sorted(_cadastro_atual().por_slug.values(), key=lambda i: i.slug)
    return [i for i in lista if i.ativa or not somente_ativas]


def normalizar_dominio(texto: str) -> str:
    """'https://WWW.Exemplo.com.br:443/x' -> 'www.exemplo.com.br'."""
    texto = texto.strip().lower().split("://", 1)[-1]
    return texto.split("/", 1)[0].split(":", 1)[0].rstrip(".")


def _identificar(cadastro: _Cadastro, scope: Scope) -> tuple[Imobiliaria | None, str]:
    cabecalhos = Headers(scope=scope)
    if pedida := cabecalhos.get(CABECALHO):
        origem = "cabecalho"
    elif pedida := QueryParams(scope["query_string"]).get(PARAMETRO):
        origem = "parametro"
    if pedida:
        imob = cadastro.por_slug.get(pedida.strip().lower())
    else:
        host = cabecalhos.get("x-forwarded-host", "").split(",")[0] or cabecalhos.get("host", "")
        host = normalizar_dominio(host)
        imob = cadastro.por_dominio.get(host) or cadastro.por_dominio.get(host.removeprefix("www."))
        origem = "dominio"
        if imob is None:
            padrao = cadastro.por_slug.get(get_settings().imobiliaria_padrao)
            return (padrao, "padrao") if padrao and padrao.ativa else (None, "")
    if imob is None or not imob.ativa:
        raise _NaoEncontrada
    return imob, origem


class IdentificarImobiliaria:
    """Middleware (ASGI puro, para o ContextVar valer na rota toda)."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        try:
            cadastro = (
                await anyio.to_thread.run_sync(_cadastro_atual)
                if _vencido()
                else _cadastro_atual()
            )
            imob, origem = _identificar(cadastro, scope)
        except _NaoEncontrada:
            resposta = JSONResponse({"detail": "Imobiliária não encontrada."}, 404)
            return await resposta(scope, receive, send)
        except Exception:
            if not scope["path"].startswith("/saude"):
                log.exception("Não foi possível ler o cadastro das imobiliárias.")
                resposta = JSONResponse(
                    {"detail": "Sistema temporariamente indisponível. Tente novamente."}, 503
                )
                return await resposta(scope, receive, send)
            imob, origem = None, ""
        token, token_origem = _atual.set(imob), _origem.set(origem)
        try:
            await self.app(scope, receive, send)
        finally:
            _atual.reset(token)
            _origem.reset(token_origem)


def cabecalho(
    x_imobiliaria: Annotated[
        str | None,
        Header(alias=CABECALHO, description="Identificador da imobiliária (ex.: marcelo)."),
    ] = None,
) -> None:
    """Só documenta o cabeçalho no Swagger; quem o lê é o middleware."""


# ------------------------------------------------------ Endereços


def endereco_publico() -> str:
    """Site da imobiliária atual ou, sem ele, o endereço do servidor."""
    imob = _atual.get()
    return ((imob and imob.site_url) or get_settings().site_url).rstrip("/")


def url_site(request: Request) -> str:
    return endereco_publico() or str(request.base_url).rstrip("/")


def estilo_marca() -> str:
    """CSS com a paleta da imobiliária atual (sobre a padrão do site); vazio
    se ela segue a padrão. As cores são validadas no cadastro (#rrggbb)."""
    imob = _atual.get()
    if imob is None or not (imob.cor_primaria or imob.cor_destaque):
        return ""
    regras = []
    if p := imob.cor_primaria:
        regras += [
            f"--navy-800:{p}",
            f"--navy-950:color-mix(in srgb,{p} 30%,#000)",
            f"--navy-900:color-mix(in srgb,{p} 55%,#000)",
            f"--navy-700:color-mix(in srgb,{p} 82%,#fff)",
            f"--navy-650:color-mix(in srgb,{p} 88%,#fff)",
            f"--navy-600:color-mix(in srgb,{p} 78%,#fff)",
            f"--blue:color-mix(in srgb,{p} 65%,#fff)",
            f"--orbe:color-mix(in srgb,{p} 70%,#fff)",
        ]
    if d := imob.cor_destaque:
        regras += [
            f"--gold:{d}",
            f"--gold-light:color-mix(in srgb,{d} 60%,#fff)",
            f"--gold-dark:color-mix(in srgb,{d} 75%,#000)",
            "--ouro:linear-gradient(135deg,var(--gold-light) 0%,var(--gold) 45%,var(--gold-dark) 100%)",
        ]
    return "<style>:root{" + ";".join(regras) + "}</style>"


def com_imobiliaria(caminho: str) -> str:
    """Acrescenta ?imob= ao link, que assim abre a imobiliária certa mesmo
    pelo endereço compartilhado do servidor."""
    separador = "&" if "?" in caminho else "?"
    return f"{caminho}{separador}{PARAMETRO}={atual().slug}"

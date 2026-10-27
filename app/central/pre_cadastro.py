"""Pré-cadastro do site institucional ("Quero me associar"): o formulário
continua abrindo o WhatsApp da associação e, antes, envia os mesmos dados
para cá (navigator.sendBeacon), onde viram um lead do Comercial."""

import re
import time
import uuid
from collections import defaultdict, deque
from urllib.parse import urlsplit

from fastapi import APIRouter, Request, Response

from app.central import models as m
from app.central import services as central
from app.core.config import get_settings
from app.core.errors import RegraNegocio
from app.core.tempo import agora

router = APIRouter(include_in_schema=False)

PERFIS = ("Corretor autônomo", "Imobiliária", "Em formação")
LIMITE_POR_HORA = 5
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_envios: dict[str, deque] = defaultdict(deque)


def _origem_permitida(request: Request) -> bool:
    """Só o site institucional (e o próprio servidor) mandam o pré-cadastro."""
    principal = get_settings().site_principal_url
    origem = request.headers.get("origin")
    if not principal or not origem:
        return True
    host = urlsplit(principal).hostname or ""
    permitidos = {host, f"www.{host.removeprefix('www.')}", host.removeprefix("www."), request.url.hostname}
    return urlsplit(origem).hostname in permitidos


def _dentro_do_limite(ip: str) -> bool:
    agora_s, fila = time.monotonic(), _envios[ip]
    while fila and agora_s - fila[0] > 3600:
        fila.popleft()
    if len(fila) >= LIMITE_POR_HORA:
        return False
    fila.append(agora_s)
    return True


def registrar(dados: dict[str, str]) -> m.LeadAssociacao:
    """Confere e grava o pré-cadastro como lead novo."""

    def campo(nome: str, maximo: int, obrigatorio: bool = True) -> str:
        valor = (dados.get(nome) or "").strip()
        if obrigatorio and not valor:
            raise RegraNegocio(f"Campo obrigatório: {nome}.")
        return valor[:maximo]

    email = campo("email", 200).lower()
    whatsapp = campo("whatsapp", 30)
    if not _EMAIL.match(email):
        raise RegraNegocio("E-mail inválido.")
    if len(re.sub(r"\D", "", whatsapp)) < 10:
        raise RegraNegocio("WhatsApp inválido.")
    perfil = campo("perfil", 40)
    if perfil not in PERFIS:
        raise RegraNegocio("Perfil inválido.")
    if dados.get("lgpd") != "on":
        raise RegraNegocio("Sem o aceite da LGPD.")
    momento = agora()
    lead = m.LeadAssociacao(
        id=str(uuid.uuid4()), nome=campo("nome", 150), email=email, whatsapp=whatsapp,
        creci=campo("creci", 30, obrigatorio=False), cidade=campo("cidade", 150), perfil=perfil,
        quer_sistema=dados.get("sistema") == "on", situacao="novo", anotacao="",
        criado_em=momento, atualizado_em=momento,
    )  # fmt: skip
    with central.sessao() as db:
        db.add(lead)
        db.commit()
    return lead


@router.post("/associacao/pre-cadastro")
async def pre_cadastro(request: Request):
    """Responde 204 sem detalhes: o site não espera resposta (o envio sai junto
    com a abertura do WhatsApp)."""
    if not _origem_permitida(request):
        return Response(status_code=403)
    dados = {k: str(v) for k, v in (await request.form()).items()}
    if dados.get("empresa_site"):  # campo escondido: só robôs preenchem
        return Response(status_code=204)
    ip = request.client.host if request.client else ""
    if not _dentro_do_limite(ip):
        return Response(status_code=429)
    try:
        registrar(dados)
    except RegraNegocio:
        return Response(status_code=422)
    return Response(status_code=204)

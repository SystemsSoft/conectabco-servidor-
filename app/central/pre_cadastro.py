"""Pré-cadastro do site institucional ("Quero me associar"): o formulário
envia os dados para cá, onde viram um lead do Comercial, e o site avisa que
um representante entrará em contato."""

import logging
import re
import time
import uuid
from collections import defaultdict, deque
from urllib.parse import urlsplit

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from app.central import models as m
from app.central import services as central
from app.core.config import get_settings
from app.core.errors import RegraNegocio
from app.core.tempo import agora

router = APIRouter(include_in_schema=False)
log = logging.getLogger("pre_cadastro")

PERFIS = ("Corretor autônomo", "Imobiliária", "Em formação")
_ROTULOS = {"nome": "Nome completo", "email": "E-mail", "whatsapp": "WhatsApp", "cidade": "Cidade / UF", "perfil": "Perfil"}
LIMITE_POR_HORA = 5
# O script do site manda quantos segundos a página ficou aberta antes do envio
# ("tempo"); robôs que postam direto não mandam ou mandam rápido demais. (Um
# campo escondido "armadilha" não serve: o preenchimento automático do
# navegador o completa e o envio de uma pessoa sumia.)
TEMPO_MINIMO = 1.5
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


def _parece_pessoa(tempo: str) -> bool:
    try:
        return float(tempo) >= TEMPO_MINIMO
    except ValueError:
        return False


def registrar(dados: dict[str, str]) -> m.LeadAssociacao:
    """Confere e grava o pré-cadastro como lead novo."""

    def campo(nome: str, maximo: int, obrigatorio: bool = True) -> str:
        valor = (dados.get(nome) or "").strip()
        if obrigatorio and not valor:
            raise RegraNegocio(f"Preencha o campo {_ROTULOS.get(nome, nome)}.")
        return valor[:maximo]

    email = campo("email", 200).lower()
    whatsapp = campo("whatsapp", 30)
    if not _EMAIL.match(email):
        raise RegraNegocio("E-mail inválido.")
    if len(re.sub(r"\D", "", whatsapp)) < 10:
        raise RegraNegocio("WhatsApp inválido: informe o DDD e o número.")
    perfil = campo("perfil", 40)
    if perfil not in PERFIS:
        raise RegraNegocio("Selecione o perfil.")
    if dados.get("lgpd") != "on":
        raise RegraNegocio("Aceite o termo de uso dos dados (LGPD) para enviar.")
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


def _resposta(request: Request, status: int, mensagem: str = "") -> Response:
    """Com a origem do site liberada (CORS), para ele ler o resultado."""
    resposta = JSONResponse({"detail": mensagem}, status_code=status) if mensagem else Response(status_code=status)
    if origem := request.headers.get("origin"):
        resposta.headers["Access-Control-Allow-Origin"] = origem
        resposta.headers["Vary"] = "Origin"
    return resposta


@router.post("/associacao/pre-cadastro")
async def pre_cadastro(request: Request):
    """204 quando o pré-cadastro foi recebido; com erro, a mensagem para o site."""
    if not _origem_permitida(request):
        return Response(status_code=403)
    dados = {k: str(v) for k, v in (await request.form()).items()}
    ip = request.client.host if request.client else ""
    if not _parece_pessoa(dados.get("tempo", "")):  # robô: "dá certo" para ele, mas não grava
        log.warning("Pré-cadastro descartado (parece robô): ip=%s tempo=%r", ip, dados.get("tempo"))
        return _resposta(request, 204)
    if not _dentro_do_limite(ip):
        return _resposta(request, 429, "Muitos envios seguidos. Tente de novo mais tarde.")
    try:
        registrar(dados)
    except RegraNegocio as e:
        return _resposta(request, 422, e.mensagem)
    return _resposta(request, 204)

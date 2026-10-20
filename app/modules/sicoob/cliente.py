"""Chamadas às APIs do Sicoob. Cada requisição fica registrada (sem o token)
para a tela de testes. Sandbox: client_id + token fixo do portal; produção
(certificado e token OAuth) ainda não é feita por aqui."""

import json
import time
from collections.abc import Callable
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.core.errors import RegraNegocio
from app.modules.sicoob.models import ChamadaSicoob

# Endereços das APIs (confirmados nos SDKs públicos do Sicoob).
BASES = {
    "sandbox": "https://sandbox.sicoob.com.br/sicoob/sandbox",
    "producao": "https://api.sicoob.com.br",
}
CAMINHOS = {
    "cobranca": "/cobranca-bancaria/v3",
    "pix": "/pix/api/v2",
    "conta": "/conta-corrente",
}
TIMEOUT = 30.0
_LIMITE_LOG = 20_000

# Os testes trocam o transporte por um simulado.
transporte_padrao: Callable[[], httpx.BaseTransport | None] = lambda: None  # noqa: E731


def _resumo(dados: Any) -> str:
    """JSON para o registro, sem PDFs em base64 e sem passar do limite."""

    def limpar(x):
        if isinstance(x, dict):
            return {k: ("<pdf omitido>" if k == "pdfBoleto" and v else limpar(v)) for k, v in x.items()}
        if isinstance(x, list):
            return [limpar(i) for i in x]
        return x

    if dados in (None, ""):
        return ""
    texto = dados if isinstance(dados, str) else json.dumps(limpar(dados), ensure_ascii=False, default=str)
    return texto[:_LIMITE_LOG]


def mensagem_erro(status: int, dados: Any) -> str:
    """Texto do erro devolvido pelo Sicoob (formatos variam por API)."""
    if isinstance(dados, dict):
        msgs = dados.get("mensagens") or dados.get("violacoes") or []
        if isinstance(msgs, list) and msgs:
            m = msgs[0]
            if isinstance(m, dict):
                return str(m.get("mensagem") or m.get("razao") or m)[:300]
        for chave in ("detail", "title", "message", "mensagem", "error_description", "error"):
            if dados.get(chave):
                return str(dados[chave])[:300]
    if status in (401, 403):
        return "Credenciais recusadas pelo Sicoob (confira o client_id e o token)."
    return f"O Sicoob respondeu HTTP {status}."


class ClienteSicoob:
    def __init__(self, db: Session, ambiente: str, client_id: str, token: str,
                 usuario_id: str | None = None):  # fmt: skip
        if ambiente != "sandbox":
            raise RegraNegocio(
                "Produção ainda não está habilitada: ela exige o certificado digital "
                "da empresa instalado no servidor. Use o Sandbox para testar."
            )
        if not client_id or not token:
            raise RegraNegocio("Informe o client_id e o token do Sandbox em Configuração.")
        self.db, self.ambiente, self.usuario_id = db, ambiente, usuario_id
        self._cabecalhos = {
            "client_id": client_id,
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    def chamar(self, api: str, metodo: str, caminho: str, operacao: str, *,
               params: dict | None = None, corpo: Any = None,
               aceitar: tuple[int, ...] = ()) -> tuple[int, Any]:  # fmt: skip
        """Faz a requisição e registra. Erros HTTP viram RegraNegocio com a
        mensagem do Sicoob (exceto os códigos em `aceitar`)."""
        url = BASES[self.ambiente] + CAMINHOS[api] + caminho
        params = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        registro = ChamadaSicoob(
            ambiente=self.ambiente, api=api, operacao=operacao, metodo=metodo,
            caminho=(CAMINHOS[api] + caminho + (("?" + str(httpx.QueryParams(params))) if params else ""))[:500],
            usuario_id=self.usuario_id, requisicao=_resumo(corpo),
        )  # fmt: skip
        inicio = time.monotonic()
        status, dados = None, None
        try:
            with httpx.Client(timeout=TIMEOUT, transport=transporte_padrao()) as http:
                r = http.request(metodo, url, params=params, json=corpo, headers=self._cabecalhos)
            status = r.status_code
            try:
                dados = r.json() if r.content else None
            except ValueError:
                dados = r.text[:2000]
            registro.status_http = status
            registro.resposta = _resumo(dados)
            registro.sucesso = 200 <= status < 300
            if not registro.sucesso and status not in aceitar:
                registro.erro = mensagem_erro(status, dados)
        except httpx.HTTPError as e:
            registro.erro = f"Sem resposta do Sicoob: {type(e).__name__}"[:500]
        registro.duracao_ms = int((time.monotonic() - inicio) * 1000)
        self.db.add(registro)
        self.db.commit()
        if registro.erro:
            raise RegraNegocio(registro.erro)
        return status, dados

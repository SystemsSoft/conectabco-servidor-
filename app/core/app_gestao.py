"""App de gestão (Flutter web) servido em /gestao em todos os endereços. Pelo
domínio de uma imobiliária ele já abre como ela: descobre quem é em
/api/v1/marca e o manifesto (app instalado) sai com o nome e as cores dela.
O build fica em GESTAO_WEB_DIR, gerado pelo deploy.sh a partir de ../gestao."""

import json
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response

from app.core.config import get_settings
from app.core.imobiliarias import identificada, origem

router = APIRouter(include_in_schema=False)
# Mudam a cada versão: o navegador sempre confere se há uma nova.
_SEM_CACHE = {"index.html", "flutter_bootstrap.js", "flutter_service_worker.js",
              "sw.js", "version.json", "manifest.json"}  # fmt: skip


def _pasta() -> Path:
    return Path(get_settings().gestao_web_dir).resolve()


@router.get("/gestao")
def raiz():
    return RedirectResponse("/gestao/", status_code=308)


@router.get("/gestao/{caminho:path}")
def arquivo(caminho: str):
    pasta = _pasta()
    if not (pasta / "index.html").is_file():
        return Response("App de gestão não publicado neste servidor.", status_code=404)
    if caminho == "manifest.json":
        return _manifesto(pasta)
    alvo = (pasta / caminho).resolve()
    if not alvo.is_relative_to(pasta) or not alvo.is_file():
        if Path(caminho).suffix:  # arquivo que não existe
            return Response("Não encontrado.", status_code=404)
        alvo = pasta / "index.html"  # rota do app
    cache = "no-cache" if alvo.name in _SEM_CACHE else "public, max-age=3600"
    return FileResponse(alvo, headers={"Cache-Control": cache})


def _manifesto(pasta: Path) -> JSONResponse:
    dados = json.loads((pasta / "manifest.json").read_text(encoding="utf-8"))
    imob = identificada() if origem() == "dominio" else None
    if imob:
        curto = imob.nome if len(imob.nome) <= 12 else imob.nome.split()[0][:12]
        dados |= {"name": imob.nome, "short_name": curto,
                  "description": f"Gestão imobiliária – {imob.nome}"}  # fmt: skip
        if imob.cor_primaria:
            dados |= {"theme_color": imob.cor_primaria, "background_color": imob.cor_primaria}
    return JSONResponse(dados, media_type="application/manifest+json",
                        headers={"Cache-Control": "no-cache"})  # fmt: skip

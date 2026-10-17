"""Site público (HTML renderizado no servidor, sem login).

Mostra só os imóveis marcados como "Publicar no site" e disponíveis, sem
dados internos (proprietário, observações, matrícula, chaves...). Os
formulários viram leads no CRM (ver services.registrar_lead).
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.database import get_db
from app.core.errors import RegraNegocio
from app.modules.arquivos.models import Arquivo
from app.modules.arquivos.services import caminho as caminho_arquivo
from app.modules.crm.enums import AnexoTipo, Finalidade, TipoImovel
from app.modules.crm.models import Imovel
from app.modules.site import schemas as s
from app.modules.site import services
from app.modules.site.enums import TipoLead

PASTA = Path(__file__).parent
templates = Jinja2Templates(directory=PASTA / "templates")
router = APIRouter(include_in_schema=False)
Db = Annotated[Session, Depends(get_db)]
POR_PAGINA = 12
_ID = re.compile(r"^[0-9a-f-]{36}$")
_YOUTUBE = re.compile(
    r"(?:youtube\.com/(?:watch\?v=|shorts/|embed/)|youtu\.be/)([\w-]{11})"
)


# ------------------------------------------------------------- Formatação


def moeda(v: float | None) -> str:
    if v is None:
        return ""
    texto = f"{v:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return "R$ " + texto.removesuffix(",00")


def numero(v: float | None) -> str:
    if v is None:
        return ""
    return f"{v:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".").removesuffix(",00")


templates.env.filters["moeda"] = moeda
# Muda a cada alteração do CSS: o navegador não usa a versão antiga do cache.
templates.env.globals["versao_css"] = max(
    int((PASTA / "static" / nome).stat().st_mtime) for nome in ("site.css", "site.js")
)
templates.env.filters["numero"] = numero


def _midia(url: str) -> str | None:
    """Endereço público de uma foto/vídeo (nunca `javascript:` etc.)."""
    if url.startswith("arquivo:"):
        return f"/midia/{url.removeprefix('arquivo:')}"
    return url if url.startswith(("https://", "http://")) else None


def _precos(i: Imovel, cfg: s.ConfiguracaoSite) -> list[dict]:
    fins = {f.finalidade for f in i.finalidades}
    itens = [
        (Finalidade.venda, i.valor_venda, ""),
        (Finalidade.locacao, i.valor_locacao, "/mês"),
        (Finalidade.temporada, i.valor_temporada, "/diária"),
    ]
    return [
        {
            "rotulo": f.rotulo,
            "valor": (moeda(v) + sufixo) if cfg.mostrar_valores and v else "Consulte",
        }
        for f, v, sufixo in itens
        if f in fins
    ]


def _cartao(i: Imovel, cfg: s.ConfiguracaoSite) -> dict:
    fotos = [u for a in i.anexos if a.tipo == AnexoTipo.foto and (u := _midia(a.url))]
    local = ", ".join(x for x in [i.bairro, i.cidade] if x)
    return {
        "codigo": i.codigo,
        "titulo": i.titulo,
        "tipo": i.tipo.rotulo,
        "finalidades": [
            f.rotulo for f in Finalidade if f in {x.finalidade for x in i.finalidades}
        ],
        "precos": _precos(i, cfg),
        "foto": fotos[0] if fotos else None,
        "local": local,
        "quartos": i.quartos,
        "suites": i.suites,
        "banheiros": i.banheiros,
        "vagas": i.vagas,
        "area": i.area_util or i.area_total,
        "destaque": i.destaque_site,
    }


def _detalhe(i: Imovel, cfg: s.ConfiguracaoSite) -> dict:
    fotos, videos = [], []
    for a in i.anexos:
        url = _midia(a.url)
        if url is None:
            continue
        if a.tipo == AnexoTipo.foto:
            fotos.append({"url": url, "titulo": a.titulo})
        elif a.tipo in (AnexoTipo.video, AnexoTipo.link):
            yt = _YOUTUBE.search(url)
            if yt:
                videos.append({"youtube": yt.group(1), "titulo": a.titulo})
            elif a.tipo == AnexoTipo.video:
                videos.append({"url": url, "titulo": a.titulo})
    rua = ", ".join(x for x in [i.logradouro, i.numero] if x)
    endereco = [rua] if i.exibir_endereco_site and rua else []
    endereco += [x for x in [i.bairro, " - ".join(y for y in [i.cidade, i.uf] if y)] if x]
    caracteristicas = [
        (rotulo, valor)
        for rotulo, valor in [
            ("Área útil", f"{numero(i.area_util)} m²" if i.area_util else ""),
            ("Área total", f"{numero(i.area_total)} m²" if i.area_total else ""),
            ("Terreno", f"{numero(i.area_terreno)} m²" if i.area_terreno else ""),
            ("Quartos", i.quartos or ""),
            ("Suítes", i.suites or ""),
            ("Banheiros", i.banheiros or ""),
            ("Vagas", i.vagas or ""),
            ("Andar", f"{i.andar}º" if i.andar else ""),
            ("Ano de construção", i.ano_construcao or ""),
            ("Mobília", i.mobiliado.rotulo),
            ("Condomínio", moeda(i.valor_condominio) if cfg.mostrar_valores else ""),
            ("IPTU", moeda(i.valor_iptu) if cfg.mostrar_valores else ""),
            ("Aceita financiamento", "Sim" if i.aceita_financiamento else ""),
            ("Aceita permuta", "Sim" if i.aceita_permuta else ""),
        ]
        if valor
    ] + [(c.nome, c.valor or "Sim") for c in i.personalizadas]
    return _cartao(i, cfg) | {
        "fotos": fotos,
        "videos": videos,
        "endereco": " • ".join(endereco),
        "descricao": i.descricao,
        "caracteristicas": caracteristicas,
        "comodidades": i.comodidades or [],
        "condominio": i.condominio_nome,
    }


def _whatsapp(numero_wa: str, texto: str) -> str:
    return f"https://wa.me/{numero_wa}?text={quote(texto)}" if numero_wa else ""


def _base(request: Request, db: Session, **extra) -> dict:
    cfg = services.configuracao(db)
    contatos = services.contatos_do_site(db, cfg)
    return {
        "request": request,
        "cfg": cfg,
        "empresa": contatos,
        "whatsapp_link": _whatsapp(
            contatos["whatsapp"], "Olá! Vim pelo site e gostaria de mais informações."
        ),
        "ano": datetime.now().year,
        "tipos_lead": TipoLead,
    } | extra


def _pagina(nome: str, ctx: dict, status: int = 200) -> Response:
    if not ctx["cfg"].no_ar:
        return templates.TemplateResponse(
            ctx["request"], "manutencao.html", ctx, status_code=503
        )
    resposta = templates.TemplateResponse(ctx["request"], nome, ctx, status_code=status)
    resposta.headers["X-Content-Type-Options"] = "nosniff"
    resposta.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return resposta


# ----------------------------------------------------------------- Páginas


@router.get("/")
def inicio(request: Request, db: Db):
    ctx = _base(request, db)
    cfg = ctx["cfg"]
    publicados = services.imoveis_publicados(db)
    destaques = [i for i in publicados if i.destaque_site] or publicados
    ctx |= {
        "destaques": [_cartao(i, cfg) for i in destaques[:6]],
        "total": len(publicados),
        "tipos": _tipos_disponiveis(publicados),
        "finalidades": Finalidade,
        "por_finalidade": {
            f.value: sum(f in {x.finalidade for x in i.finalidades} for i in publicados)
            for f in Finalidade
        },
        "bairros": len({(i.bairro, i.cidade) for i in publicados if i.bairro}),
        "pagina_atual": "inicio",
    }
    return _pagina("inicio.html", ctx)


def _tipos_disponiveis(imoveis: list[Imovel]) -> list[TipoImovel]:
    usados = {i.tipo for i in imoveis}
    return [t for t in TipoImovel if t in usados]


def _preco_para(i: Imovel, finalidade: Finalidade | None) -> float | None:
    if finalidade == Finalidade.locacao:
        return i.valor_locacao
    if finalidade == Finalidade.temporada:
        return i.valor_temporada
    return i.valor_venda or i.valor_locacao or i.valor_temporada


def _int(texto: str | None) -> int | None:
    digitos = re.sub(r"\D", "", texto or "")
    return int(digitos) if digitos else None


@router.get("/imoveis")
def imoveis(
    request: Request,
    db: Db,
    finalidade: str = "",
    tipo: str = "",
    q: str = "",
    quartos: str = "",
    preco_max: str = "",
    ordem: str = "recentes",
    pagina: str = "1",
):
    ctx = _base(request, db)
    cfg = ctx["cfg"]
    publicados = services.imoveis_publicados(db)
    fin = Finalidade(finalidade) if finalidade in Finalidade._value2member_map_ else None
    tp = TipoImovel(tipo) if tipo in TipoImovel._value2member_map_ else None
    minimo_quartos = _int(quartos)
    maximo = _int(preco_max)
    termo = q.strip().lower()

    def passa(i: Imovel) -> bool:
        if fin and fin not in {f.finalidade for f in i.finalidades}:
            return False
        if tp and i.tipo != tp:
            return False
        if minimo_quartos and i.quartos < minimo_quartos:
            return False
        preco = _preco_para(i, fin)
        if maximo and (preco is None or preco > maximo):
            return False
        if termo:
            texto = " ".join([i.codigo, i.titulo, i.bairro, i.cidade]).lower()
            return termo in texto
        return True

    achados = [i for i in publicados if passa(i)]
    if ordem in ("menor", "maior"):
        achados.sort(
            key=lambda i: _preco_para(i, fin) or 0, reverse=ordem == "maior"
        )
    total = len(achados)
    paginas = max(1, -(-total // POR_PAGINA))
    atual = min(max(_int(pagina) or 1, 1), paginas)
    filtros = {
        "finalidade": finalidade, "tipo": tipo, "q": q, "quartos": quartos,
        "preco_max": preco_max, "ordem": ordem,
    }  # fmt: skip
    ctx |= {
        "imoveis": [
            _cartao(i, cfg)
            for i in achados[(atual - 1) * POR_PAGINA : atual * POR_PAGINA]
        ],
        "total": total,
        "pagina": atual,
        "paginas": paginas,
        "filtros": filtros,
        "query_pagina": lambda n: "?" + urlencode({**filtros, "pagina": n}),
        "tipos": _tipos_disponiveis(publicados),
        "finalidades": Finalidade,
        "pagina_atual": "imoveis",
    }
    return _pagina("imoveis.html", ctx)


@router.get("/imovel/{codigo}")
def imovel(request: Request, codigo: str, db: Db):
    ctx = _base(request, db, pagina_atual="imoveis")
    i = services.imovel_publicado(db, codigo)
    if i is None:
        return _pagina("nao_encontrado.html", ctx, 404)
    d = _detalhe(i, ctx["cfg"])
    ctx |= {
        "imovel": d,
        "whatsapp_imovel": _whatsapp(
            ctx["empresa"]["whatsapp"],
            f"Olá! Tenho interesse no imóvel {d['codigo']} – {d['titulo']}.",
        ),
        "hoje": datetime.now().date().isoformat(),
    }
    return _pagina("imovel.html", ctx)


@router.get("/anuncie")
def anuncie(request: Request, db: Db):
    ctx = _base(request, db, pagina_atual="anuncie")
    if not ctx["cfg"].mostrar_anuncie:
        return _pagina("nao_encontrado.html", ctx, 404)
    return _pagina("anuncie.html", ctx)


@router.get("/contato")
def contato(request: Request, db: Db):
    return _pagina("contato.html", _base(request, db, pagina_atual="contato"))


@router.get("/obrigado")
def obrigado(request: Request, db: Db):
    return _pagina("obrigado.html", _base(request, db))


def _ip(request: Request) -> str:
    encaminhado = request.headers.get("x-forwarded-for", "")
    return encaminhado.split(",")[0].strip() or (
        request.client.host if request.client else "?"
    )


@router.post("/enviar")
def enviar(
    request: Request,
    db: Db,
    nome: Annotated[str, Form()] = "",
    email: Annotated[str, Form()] = "",
    telefone: Annotated[str, Form()] = "",
    mensagem: Annotated[str, Form()] = "",
    tipo: Annotated[str, Form()] = "contato",
    imovel: Annotated[str, Form()] = "",
    data_visita: Annotated[str, Form()] = "",
    horario_visita: Annotated[str, Form()] = "",
    consentimento: Annotated[str, Form()] = "",
    retorno: Annotated[str, Form()] = "/",
    empresa: Annotated[str, Form()] = "",  # isca para robôs: fica oculto
):
    # Só caminhos do próprio site (evita redirecionar para fora).
    retorno = retorno if retorno.startswith("/") and not retorno.startswith("//") else "/"
    cfg = services.configuracao(db)
    if not cfg.no_ar:
        return RedirectResponse("/", status_code=303)
    if empresa:  # robô: finge que deu certo
        return RedirectResponse("/obrigado", status_code=303)
    try:
        services.conferir_limite(_ip(request))
        visita = None
        if data_visita:
            try:
                visita = datetime.fromisoformat(
                    f"{data_visita}T{horario_visita or '10:00'}"
                )
            except ValueError:
                raise RegraNegocio("Data da visita inválida.") from None
        entrada = s.LeadEntrada(
            tipo=tipo if tipo in TipoLead._value2member_map_ else TipoLead.contato,
            nome=nome[:200],
            email=email[:200],
            telefone=telefone[:30],
            mensagem=mensagem[:3000],
            imovel_codigo=imovel[:20],
            data_visita=visita,
            consentimento=consentimento in ("on", "sim", "true", "1"),
            pagina=retorno[:300],
        )
        services.registrar_lead(db, entrada, cfg)
        services.contar_envio(_ip(request))
    except RegraNegocio as e:
        separador = "&" if "?" in retorno else "?"
        return RedirectResponse(
            f"{retorno}{separador}{urlencode({'erro': e.mensagem})}#formulario",
            status_code=303,
        )
    return RedirectResponse("/obrigado", status_code=303)


# ------------------------------------------------------- Mídia e buscadores


@router.get("/midia/{arquivo_id}")
def midia(arquivo_id: str, db: Db):
    if not _ID.match(arquivo_id) or not services.midia_publica(db, arquivo_id):
        return Response("Não encontrado.", status_code=404)
    a = db.get(Arquivo, arquivo_id)
    caminho = caminho_arquivo(arquivo_id)
    if a is None or not caminho.is_file():
        return Response("Não encontrado.", status_code=404)
    return FileResponse(
        caminho,
        media_type=a.tipo_mime,
        headers={
            "Cache-Control": "public, max-age=86400",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/logo")
def logo(db: Db):
    from app.modules.personalizacao.models import DadosEmpresa

    e = db.get(DadosEmpresa, 1)
    if e and e.logo:
        return Response(
            e.logo,
            media_type=e.logo_tipo,
            headers={"Cache-Control": "public, max-age=3600"},
        )
    return FileResponse(PASTA / "static" / "logo.png")


def _url_site(request: Request) -> str:
    return (get_settings().site_url or str(request.base_url)).rstrip("/")


@router.get("/robots.txt")
def robots(request: Request):
    return Response(
        f"User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /docs\nDisallow: /inquilino\n"
        f"Sitemap: {_url_site(request)}/sitemap.xml\n",
        media_type="text/plain",
    )


@router.get("/sitemap.xml")
def sitemap(request: Request, db: Db):
    base = _url_site(request)
    caminhos = ["/", "/imoveis", "/contato"]
    if services.configuracao(db).mostrar_anuncie:
        caminhos.append("/anuncie")
    caminhos += [f"/imovel/{i.codigo}" for i in services.imoveis_publicados(db)]
    urls = "".join(f"<url><loc>{base}{c}</loc></url>" for c in caminhos)
    return Response(
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{urls}</urlset>',
        media_type="application/xml",
    )

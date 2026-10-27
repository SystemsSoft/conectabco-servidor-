"""Painel da plataforma (/plataforma): cadastro das imobiliárias — banco
próprio, domínios, paleta de cores, logotipo, situação e administrador de
cada uma. Só abre pelo endereço do servidor, nunca pelo domínio de uma
imobiliária."""

import socket
from dataclasses import fields
from pathlib import Path
from typing import Annotated
from urllib.parse import quote

import sqlalchemy as sa
from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.central import acesso
from app.central import comercial as com
from app.central import contratacao as cc
from app.central import contratante as ct
from app.central import financeiro as fin
from app.central import infraestrutura as infra
from app.central import models as m
from app.central import representantes as rep
from app.central import services as central
from app.core.config import get_settings
from app.core.database import fabrica
from app.core.errors import RegraNegocio
from app.core.formatacao import formatar_moeda
from app.core.tempo import agora
from app.core.imobiliarias import Imobiliaria, buscar, identificada, normalizar_dominio, usar

PASTA = Path(__file__).parent
templates = Jinja2Templates(directory=PASTA / "templates")
templates.env.filters.update(tamanho=infra.tamanho, dinheiro=infra.dinheiro,
                             duracao=infra.duracao, mes=infra.mes)  # fmt: skip
templates.env.globals["porcento"] = infra.porcento


def _digitos(texto: str) -> str:
    return "".join(c for c in texto or "" if c.isdigit())


def _cpf_cnpj(texto: str) -> str:
    d = _digitos(texto)
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    return texto


def _reais(valor) -> str:
    return formatar_moeda(float(valor)) if valor is not None else "—"


def _decimal_br(valor) -> str:
    return f"{float(valor):.2f}".replace(".", ",") if valor is not None else ""


templates.env.filters.update(digitos=_digitos, cpf_cnpj=_cpf_cnpj, reais=_reais, decimal_br=_decimal_br)
COR_PRIMARIA, COR_DESTAQUE = "#061a48", "#f5c432"  # a paleta padrão do site

MENSAGENS = {
    "criada": "Imobiliária criada: banco, tabelas e administrador prontos.",
    "salva": "Alterações salvas.",
    "logo": "Logotipo atualizado.",
    "logo-removido": "Logotipo removido.",
    "dominio": "Domínio adicionado. Falta apontar o DNS e ligar o HTTPS (veja abaixo).",
    "dominio-removido": "Domínio removido.",
    "ativada": "Imobiliária ativada.",
    "desativada": "Imobiliária desativada: API, site e portais deixam de abrir.",
    "admin": "Administrador salvo: ele já pode entrar no app de gestão.",
    "contrato": "Dados do contratante salvos.",
    "plano": "Plano salvo.",
    "lead": "Lead atualizado.",
    "pagamento": "1º pagamento confirmado: a Tecnologia já pode iniciar a implantação.",
    "pagamento-desfeito": "Confirmação do 1º pagamento desfeita.",
    "documento": "Documento guardado.",
    "documento-removido": "Documento removido.",
    "aws": "Dados da AWS atualizados (consultados no máximo a cada 10 minutos).",
    "solicitacao-criada": "Solicitação criada: quando for implantar, use o botão Implantar.",
    "solicitacao": "Solicitação atualizada: o representante já vê a nova situação.",
    "representante": "Representante salvo.",
    "representante-criado": "Representante cadastrado: envie a ele o usuário, a senha e o endereço /representante.",
}


def _so_pelo_servidor(request: Request) -> None:
    imob = identificada()
    host = normalizar_dominio(request.headers.get("host", ""))
    if imob and (host in imob.dominios or host.removeprefix("www.") in imob.dominios):
        raise HTTPException(404)


router = APIRouter(prefix="/plataforma", include_in_schema=False,
                   dependencies=[Depends(_so_pelo_servidor)])  # fmt: skip


def _db():
    with central.sessao() as db:
        yield db


Db = Annotated[Session, Depends(_db)]


def admin_logado(request: Request, db: Db) -> m.Administrador:
    a = acesso.do_token(db, request.cookies.get(acesso.COOKIE))
    if a is None:
        raise HTTPException(303, headers={"Location": "/plataforma/entrar"})
    return a


Admin = Annotated[m.Administrador, Depends(admin_logado)]


async def _form_contrato(request: Request) -> ct.DadosContrato:
    """Campos contrato_* do formulário (o Starlette guarda o form já lido)."""
    return ct.DadosContrato.do_formulario(await request.form())


Contrato = Annotated[ct.DadosContrato, Depends(_form_contrato)]


def _conferir(admin: m.Administrador, csrf: str) -> None:
    if not acesso.csrf_valido(admin, csrf):
        raise HTTPException(403, "Formulário expirado: recarregue a página.")


def _pagina(request: Request, nome: str, ctx: dict, status: int = 200) -> Response:
    resposta = templates.TemplateResponse(request, nome, ctx, status_code=status)
    resposta.headers.update({
        "Cache-Control": "no-store",
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
        "X-Robots-Tag": "noindex",
        "Referrer-Policy": "same-origin",
    })  # fmt: skip
    return resposta


def _ir(caminho: str, msg: str = "", erro: str = "") -> RedirectResponse:
    if msg:
        caminho += f"?msg={msg}"
    elif erro:
        caminho += f"?erro={quote(erro)}"
    return RedirectResponse(caminho, status_code=303)


def _base(request: Request, admin: m.Administrador | None, **extra) -> dict:
    novas = pendentes = leads_novos = 0
    if admin:  # contadores nas abas: solicitações novas, pagamentos a confirmar e leads
        with central.sessao() as db:
            novas, pendentes = rep.contagem(db)["nova"], fin.contagem(db)["aguardando"]
            leads_novos = com.contagem_leads(db)["novo"]
    return {
        "pendentes": pendentes,
        "leads_novos": leads_novos,
        "admin": admin,
        "novas": novas,
        "csrf": acesso.token_csrf(admin) if admin else "",
        "msg": MENSAGENS.get(request.query_params.get("msg", ""), ""),
        "erro": request.query_params.get("erro", ""),
        "padrao": {"primaria": COR_PRIMARIA, "destaque": COR_DESTAQUE},
    } | extra


def _imobiliaria(slug: str) -> Imobiliaria:
    """A do cadastro em memória, relido agora (pode ter acabado de mudar)."""
    from app.core.imobiliarias import limpar_cadastro

    limpar_cadastro()
    imob = buscar(slug)
    if imob is None:
        raise HTTPException(404)
    return imob


# ------------------------------------------------------------- Entrar


@router.get("/entrar")
def entrar_pagina(request: Request, db: Db):
    if acesso.do_token(db, request.cookies.get(acesso.COOKIE)):
        return _ir("/plataforma")
    return _pagina(request, "entrar.html", _base(request, None))


@router.post("/entrar")
def entrar(request: Request, db: Db, login: Annotated[str, Form()] = "",
           senha: Annotated[str, Form()] = ""):  # fmt: skip
    try:
        a = acesso.autenticar(db, login, senha)
    except RegraNegocio as e:
        return _pagina(request, "entrar.html", _base(request, None, erro=e.mensagem, login=login), 422)
    resposta = _ir("/plataforma")
    resposta.set_cookie(
        acesso.COOKIE, acesso.criar_token(a), max_age=acesso.SESSAO_HORAS * 3600,
        httponly=True, samesite="strict", secure=request.url.scheme == "https", path="/plataforma",
    )  # fmt: skip
    return resposta


@router.post("/sair")
def sair(admin: Admin, csrf: Annotated[str, Form()] = ""):
    _conferir(admin, csrf)
    resposta = _ir("/plataforma/entrar")
    resposta.delete_cookie(acesso.COOKIE, path="/plataforma")
    return resposta


# ---------------------------------------------------------- Imobiliárias


@router.get("")
def lista(request: Request, db: Db, admin: Admin):
    imobiliarias = db.scalars(sa.select(m.Imobiliaria).order_by(m.Imobiliaria.nome)).all()
    return _pagina(request, "lista.html", _base(request, admin, imobiliarias=imobiliarias))


@router.get("/nova")
def nova_pagina(request: Request, db: Db, admin: Admin, solicitacao: str = ""):
    """Com ?solicitacao=, já vem preenchida com os dados do corretor."""
    dados, contrato, logo_enviado = {}, ct.DadosContrato(), None
    if solicitacao:
        s = rep.solicitacao(db, solicitacao)
        try:
            fin.exigir_pagamento(s)
        except RegraNegocio as e:
            return _ir("/plataforma/solicitacoes", erro=e.mensagem)
        assinado = cc.da_solicitacao(db, s.id)  # contratou pelo site: o contratante do contrato
        contrato = cc.dados_para_contratante(assinado) if assinado else ct.da_solicitacao(s)
        logo_enviado = fin.logo(db, s)
        dados = {"solicitacao": s.id, "nome": s.nome_imobiliaria, "slug": rep.sugestao_de_slug(s.nome_imobiliaria),
                 "dominios": s.dominio, "site_url": f"https://{s.dominio}" if s.dominio else "",
                 "admin_nome": s.nome, "admin_login": s.email.split("@")[0]}  # fmt: skip
    return _pagina(request, "nova.html", _base(request, admin, dados=dados, contrato=contrato, ufs=rep.UFS,
                                               logo_enviado=logo_enviado))  # fmt: skip


@router.post("/nova")
def nova(
    request: Request, admin: Admin, contrato: Contrato,
    csrf: Annotated[str, Form()] = "",
    slug: Annotated[str, Form()] = "", nome: Annotated[str, Form()] = "",
    dominios: Annotated[str, Form()] = "", site_url: Annotated[str, Form()] = "",
    cor_primaria: Annotated[str, Form()] = "", cor_destaque: Annotated[str, Form()] = "",
    admin_nome: Annotated[str, Form()] = "", admin_login: Annotated[str, Form()] = "",
    admin_senha: Annotated[str, Form()] = "",
    solicitacao: Annotated[str, Form()] = "",
    mensalidade: Annotated[str, Form()] = "150,00", dia_vencimento: Annotated[str, Form()] = "5",
    logo: UploadFile | None = None,
):  # fmt: skip
    """Cria o banco, as tabelas, o cadastro e o administrador da imobiliária."""
    from app.modules.equipe.services import _validar_login, _validar_senha, aparar, criar_administrador

    _conferir(admin, csrf)
    dados = {"slug": slug, "nome": nome, "dominios": dominios, "site_url": site_url,
             "cor_primaria": cor_primaria, "cor_destaque": cor_destaque,
             "admin_nome": admin_nome, "admin_login": admin_login, "solicitacao": solicitacao,
             "mensalidade": mensalidade, "dia_vencimento": dia_vencimento}  # fmt: skip
    try:
        conteudo = logo.file.read(central.LOGO_MAX + 1) if logo and logo.filename else None
        if not conteudo and solicitacao:  # sem outro escolhido: o enviado pelo contratante
            with central.sessao() as db:
                if enviado := fin.logo(db, rep.solicitacao(db, solicitacao)):
                    conteudo = fin.conteudo(enviado)
        if conteudo:
            central.validar_logo(conteudo)
        if solicitacao:  # antes de criar o banco: a trava do financeiro
            with central.sessao() as db:
                fin.exigir_pagamento(rep.solicitacao(db, solicitacao))
        valores_contrato = ct.validar(contrato)
        plano = com.validar_plano(mensalidade, dia_vencimento)
        if not admin_nome.strip():
            raise RegraNegocio("Informe o nome do administrador da imobiliária.")
        _validar_login(aparar(admin_login))
        _validar_senha(aparar(admin_senha))
        imob = central.criar_imobiliaria(
            slug, nome, site_url=site_url, dominios=dominios.replace(",", "\n").split(),
            cor_primaria=_cor(cor_primaria, COR_PRIMARIA),
            cor_destaque=_cor(cor_destaque, COR_DESTAQUE), logo=conteudo,
        )  # fmt: skip
        with usar(imob), fabrica(imob)() as db:
            criar_administrador(db, admin_nome, admin_login, admin_senha)
    except RegraNegocio as e:
        return _pagina(request, "nova.html", _base(request, admin, dados=dados, contrato=contrato,
                                                   ufs=rep.UFS, erro=e.mensagem), 422)  # fmt: skip
    with central.sessao() as db:
        ct.salvar(db, imob.slug, valores_contrato)
        com.definir_plano(db, imob.slug, *plano)
    if solicitacao:  # a solicitação do representante vira implantada
        with central.sessao() as db:
            rep.atualizar(db, solicitacao, "implantada",
                          f"Sistema implantado: {imob.nome}.", imobiliaria_slug=imob.slug)  # fmt: skip
    return _ir(f"/plataforma/{imob.slug}", "criada")


# ------------------------------------------------------- Infraestrutura


@router.get("/infraestrutura")
def infraestrutura(request: Request, db: Db, admin: Admin):
    ctx = _base(request, admin, aws=infra.da_aws(), maquina=infra.maquina(),
                banco=infra.banco(db), bucket_nome=get_settings().aws_bucket)  # fmt: skip
    return _pagina(request, "infraestrutura.html", ctx)


# -------------------------------------------------------------- Financeiro


@router.get("/financeiro")
def financeiro(request: Request, db: Db, admin: Admin, filtro: str = "aguardando"):
    filtro = filtro if filtro in fin.FILTROS else "aguardando"
    ctx = _base(request, admin, solicitacoes=fin.solicitacoes(db, filtro), filtro=filtro, filtros=fin.FILTROS,
                contagem=fin.contagem(db), situacoes=rep.SITUACOES)  # fmt: skip
    return _pagina(request, "financeiro.html", ctx)


@router.get("/financeiro/documentos/{doc_id}")
def abrir_documento(doc_id: str, db: Db, admin: Admin):
    d = fin.documento(db, doc_id)
    loja, chave = fin.onde(d)
    inline = d.tipo_mime.startswith(("image/", "application/pdf"))
    if url := loja.link(chave, d.tipo_mime, d.nome, inline, "private, no-store"):
        return RedirectResponse(url, status_code=307, headers={"Cache-Control": "no-store",
                                                               "Referrer-Policy": "no-referrer"})  # fmt: skip
    if not loja.existe(chave):
        raise HTTPException(404)
    return FileResponse(loja.caminho(chave), media_type=d.tipo_mime, filename=d.nome,
                        content_disposition_type="inline" if inline else "attachment",
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})  # fmt: skip


@router.post("/financeiro/documentos/{doc_id}/remover")
def remover_documento(doc_id: str, db: Db, admin: Admin, csrf: Annotated[str, Form()] = ""):
    _conferir(admin, csrf)
    d = fin.documento(db, doc_id)
    destino = f"/plataforma/financeiro/{d.solicitacao_id}"
    fin.remover_documento(db, d)
    return _ir(destino, "documento-removido")


@router.get("/financeiro/{id_}")
def financeiro_solicitacao(id_: str, request: Request, db: Db, admin: Admin):
    s = rep.solicitacao(db, id_)
    contratante = ct.obter(db, s.imobiliaria_slug) if s.imobiliaria_slug else None
    ctx = _base(request, admin, s=s, documentos=fin.documentos(db, s), tipos=fin.TIPOS, situacoes=rep.SITUACOES,
                contratante=contratante, hoje=agora().date().isoformat(), contrato_digital=cc.da_solicitacao(db, s.id),
                metodos=cc.METODOS, validador=cc.VALIDADOR_ITI)  # fmt: skip
    return _pagina(request, "financeiro_solicitacao.html", ctx)


@router.post("/financeiro/{id_}/pagamento")
def confirmar_pagamento(id_: str, db: Db, admin: Admin, csrf: Annotated[str, Form()] = "",
                        data_pagamento: Annotated[str, Form()] = "", observacao: Annotated[str, Form()] = ""):  # fmt: skip
    _conferir(admin, csrf)
    try:
        fin.confirmar_pagamento(db, rep.solicitacao(db, id_), admin, data_pagamento, observacao)
    except RegraNegocio as e:
        return _ir(f"/plataforma/financeiro/{id_}", erro=e.mensagem)
    return _ir(f"/plataforma/financeiro/{id_}", "pagamento")


@router.post("/financeiro/{id_}/pagamento/desfazer")
def desfazer_pagamento(id_: str, db: Db, admin: Admin, csrf: Annotated[str, Form()] = ""):
    _conferir(admin, csrf)
    try:
        fin.desfazer_pagamento(db, rep.solicitacao(db, id_))
    except RegraNegocio as e:
        return _ir(f"/plataforma/financeiro/{id_}", erro=e.mensagem)
    return _ir(f"/plataforma/financeiro/{id_}", "pagamento-desfeito")


@router.post("/financeiro/{id_}/documentos")
def enviar_documento(id_: str, db: Db, admin: Admin, arquivo: UploadFile, csrf: Annotated[str, Form()] = "",
                     tipo: Annotated[str, Form()] = "", descricao: Annotated[str, Form()] = ""):  # fmt: skip
    _conferir(admin, csrf)
    try:
        fin.enviar_documento(db, rep.solicitacao(db, id_), admin, arquivo.file, arquivo.filename or "", tipo, descricao)
    except RegraNegocio as e:
        return _ir(f"/plataforma/financeiro/{id_}", erro=e.mensagem)
    return _ir(f"/plataforma/financeiro/{id_}", "documento")


# --------------------------------------------------------------- Comercial


def _periodo(periodo: str) -> str:
    return periodo if periodo in com.PERIODOS else "12m"


@router.get("/comercial")
def comercial_funil(request: Request, db: Db, admin: Admin, periodo: str = "12m"):
    periodo = _periodo(periodo)
    ctx = _base(request, admin, periodo=periodo, periodos=com.PERIODOS,
                funil=com.funil(db, com.inicio_do_periodo(periodo)))  # fmt: skip
    return _pagina(request, "comercial_funil.html", ctx)


@router.get("/comercial/representantes")
def comercial_representantes(request: Request, db: Db, admin: Admin, periodo: str = "12m"):
    periodo = _periodo(periodo)
    ctx = _base(request, admin, periodo=periodo, periodos=com.PERIODOS,
                desempenho=com.desempenho(db, com.inicio_do_periodo(periodo)),
                sem_envio=com.sem_envio(db), dias=com.SEM_ENVIO_DIAS)  # fmt: skip
    return _pagina(request, "comercial_representantes.html", ctx)


@router.get("/comercial/receita")
def comercial_receita(request: Request, db: Db, admin: Admin):
    r = com.receita(db)
    maior = max((x.receita for x in r.meses), default=0) or 1
    ctx = _base(request, admin, receita=r, maior=maior)
    return _pagina(request, "comercial_receita.html", ctx)


@router.get("/comercial/leads")
def comercial_leads(request: Request, db: Db, admin: Admin, situacao: str = "novo"):
    situacao = situacao if situacao in com.SITUACOES_LEAD or situacao == "todos" else "novo"
    ctx = _base(request, admin, leads=com.leads(db, situacao), situacao=situacao,
                situacoes=com.SITUACOES_LEAD, contagem=com.contagem_leads(db))  # fmt: skip
    return _pagina(request, "comercial_leads.html", ctx)


@router.post("/comercial/leads/{id_}")
def atualizar_lead(id_: str, db: Db, admin: Admin, csrf: Annotated[str, Form()] = "",
                   situacao: Annotated[str, Form()] = "", anotacao: Annotated[str, Form()] = "",
                   voltar: Annotated[str, Form()] = "novo"):  # fmt: skip
    _conferir(admin, csrf)
    destino = f"/plataforma/comercial/leads?situacao={quote(voltar)}"
    try:
        com.atualizar_lead(db, id_, situacao, anotacao)
    except RegraNegocio as e:
        return RedirectResponse(f"{destino}&erro={quote(e.mensagem)}", status_code=303)
    return RedirectResponse(f"{destino}&msg=lead", status_code=303)


@router.post("/infraestrutura")
def atualizar_infraestrutura(admin: Admin, csrf: Annotated[str, Form()] = ""):
    _conferir(admin, csrf)
    infra.da_aws(forcar=True)
    return _ir("/plataforma/infraestrutura", "aws")


# ---------------------------------------------- Solicitações de implantação


@router.get("/solicitacoes")
def solicitacoes(request: Request, db: Db, admin: Admin, situacao: str = "nova"):
    situacao = situacao if situacao in rep.SITUACOES or situacao == "todas" else "nova"
    lista = rep.solicitacoes(db, "" if situacao == "todas" else situacao)
    ctx = _base(request, admin, solicitacoes=lista, situacao=situacao,
                situacoes=rep.SITUACOES, contagem=rep.contagem(db))  # fmt: skip
    return _pagina(request, "solicitacoes.html", ctx)


@router.get("/solicitacoes/nova")
def nova_solicitacao_pagina(request: Request, db: Db, admin: Admin, lead: str = ""):
    """Com ?lead=, vem preenchida com o pré-cadastro do site."""
    dados = com.dados_para_solicitacao(com.lead(db, lead)) if lead else rep.DadosCorretor()
    ctx = _base(request, admin, dados=dados, ufs=rep.UFS, lead=lead)
    return _pagina(request, "solicitacao_nova.html", ctx)


@router.post("/solicitacoes/nova")
async def nova_solicitacao(request: Request, db: Db, admin: Admin):
    """Corretor que chegou direto à associação: mesmo fluxo das solicitações
    dos representantes, em nome do administrador."""
    formulario = await request.form()
    _conferir(admin, str(formulario.get("csrf", "")))
    dados = rep.DadosCorretor(**{f.name: str(formulario.get(f.name, "")) for f in fields(rep.DadosCorretor)})
    lead = str(formulario.get("lead", ""))
    try:
        s = rep.enviar_solicitacao(db, admin, dados)
    except RegraNegocio as e:
        ctx = _base(request, admin, dados=dados, ufs=rep.UFS, lead=lead, erro=e.mensagem)
        return _pagina(request, "solicitacao_nova.html", ctx, 422)
    if lead:  # o lead do site vira esta solicitação
        com.converter(db, lead, s.id)
    return _ir("/plataforma/solicitacoes", "solicitacao-criada")


@router.post("/solicitacoes/{id_}")
def atualizar_solicitacao(id_: str, db: Db, admin: Admin, csrf: Annotated[str, Form()] = "",
                          situacao: Annotated[str, Form()] = "", resposta: Annotated[str, Form()] = "",
                          voltar: Annotated[str, Form()] = "nova"):  # fmt: skip
    _conferir(admin, csrf)
    destino = f"/plataforma/solicitacoes?situacao={quote(voltar)}"
    try:
        rep.atualizar(db, id_, situacao, resposta)
    except RegraNegocio as e:
        return RedirectResponse(f"{destino}&erro={quote(e.mensagem)}", status_code=303)
    return RedirectResponse(f"{destino}&msg=solicitacao", status_code=303)


# ---------------------------------------------------------- Representantes


@router.get("/representantes")
def representantes(request: Request, db: Db, admin: Admin):
    ctx = _base(request, admin, representantes=rep.representantes(db), dados={})
    return _pagina(request, "representantes.html", ctx)


@router.post("/representantes")
def criar_representante(
    request: Request, db: Db, admin: Admin, csrf: Annotated[str, Form()] = "",
    nome: Annotated[str, Form()] = "", login: Annotated[str, Form()] = "",
    email: Annotated[str, Form()] = "", telefone: Annotated[str, Form()] = "",
    regiao: Annotated[str, Form()] = "", senha: Annotated[str, Form()] = "",
):  # fmt: skip
    _conferir(admin, csrf)
    try:
        rep.salvar_representante(db, None, nome, login, email, telefone, regiao, senha)
    except RegraNegocio as e:
        dados = {"nome": nome, "login": login, "email": email, "telefone": telefone, "regiao": regiao}
        ctx = _base(request, admin, representantes=rep.representantes(db), dados=dados, erro=e.mensagem)
        return _pagina(request, "representantes.html", ctx, 422)
    return _ir("/plataforma/representantes", "representante-criado")


@router.get("/representantes/{id_}")
def representante(id_: str, request: Request, db: Db, admin: Admin):
    r = rep.representante(db, id_)
    ctx = _base(request, admin, r=r, solicitacoes=rep.solicitacoes(db, representante_id=r.id),
                situacoes=rep.SITUACOES)  # fmt: skip
    return _pagina(request, "representante.html", ctx)


@router.post("/representantes/{id_}")
def salvar_representante(
    id_: str, db: Db, admin: Admin, csrf: Annotated[str, Form()] = "",
    nome: Annotated[str, Form()] = "", login: Annotated[str, Form()] = "",
    email: Annotated[str, Form()] = "", telefone: Annotated[str, Form()] = "",
    regiao: Annotated[str, Form()] = "", senha: Annotated[str, Form()] = "",
    ativo: Annotated[str, Form()] = "",
):  # fmt: skip
    _conferir(admin, csrf)
    try:
        rep.salvar_representante(db, id_, nome, login, email, telefone, regiao, senha, ativo == "1")
    except RegraNegocio as e:
        return _ir(f"/plataforma/representantes/{id_}", erro=e.mensagem)
    return _ir(f"/plataforma/representantes/{id_}", "representante")


def _cor(cor: str, padrao: str) -> str:
    """A cor padrão não é gravada: a imobiliária segue a paleta do sistema."""
    return "" if cor.strip().lower() == padrao else cor


def _ip_do_servidor(request: Request) -> str:
    try:
        return socket.gethostbyname(request.url.hostname or "")
    except OSError:
        return ""


def _aponta(dominio: str, ip: str) -> bool:
    try:
        return ip in {i[4][0] for i in socket.getaddrinfo(dominio, None, socket.AF_INET)}
    except OSError:
        return False


@router.get("/{slug}")
def detalhe(slug: str, request: Request, db: Db, admin: Admin):
    from app.modules.equipe.enums import PerfilAcesso
    from app.modules.equipe.models import Usuario

    r = db.get(m.Imobiliaria, slug)
    if r is None:
        raise HTTPException(404)
    imob = _imobiliaria(slug)
    ip = _ip_do_servidor(request)
    try:
        with fabrica(imob)() as tdb:
            admins = tdb.scalars(
                sa.select(Usuario).where(Usuario.perfil == PerfilAcesso.administrador)
                .order_by(Usuario.nome)
            ).all()  # fmt: skip
        tem_logo = central.logo(imob) is not None
        erro_banco = ""
    except Exception as e:  # noqa: BLE001 - mostra o problema no painel
        admins, tem_logo, erro_banco = [], False, str(e)[:300]
    ctx = _base(
        request, admin, r=r, imob=imob, ip=ip, admins=admins, tem_logo=tem_logo,
        erro_banco=erro_banco, dns={d.dominio: _aponta(d.dominio, ip) for d in r.dominios},
        endereco=f"{request.url.scheme}://{request.url.netloc}",
        contrato=ct.DadosContrato.do_registro(salvo := ct.obter(db, slug)), contrato_salvo=salvo is not None,
        ufs=rep.UFS,
    )  # fmt: skip
    return _pagina(request, "imobiliaria.html", ctx)


@router.post("/{slug}/plano")
def salvar_plano(slug: str, db: Db, admin: Admin, csrf: Annotated[str, Form()] = "",
                 mensalidade: Annotated[str, Form()] = "", dia_vencimento: Annotated[str, Form()] = ""):  # fmt: skip
    _conferir(admin, csrf)
    try:
        com.definir_plano(db, slug, *com.validar_plano(mensalidade, dia_vencimento))
    except RegraNegocio as e:
        return _ir(f"/plataforma/{slug}", erro=e.mensagem)
    return _ir(f"/plataforma/{slug}", "plano")


@router.post("/{slug}/contrato")
def salvar_contrato(slug: str, db: Db, admin: Admin, contrato: Contrato, csrf: Annotated[str, Form()] = ""):
    _conferir(admin, csrf)
    if db.get(m.Imobiliaria, slug) is None:
        raise HTTPException(404)
    try:
        ct.salvar(db, slug, ct.validar(contrato))
    except RegraNegocio as e:
        return _ir(f"/plataforma/{slug}", erro=e.mensagem)
    return _ir(f"/plataforma/{slug}", "contrato")


@router.post("/{slug}")
def salvar(
    slug: str, db: Db, admin: Admin, csrf: Annotated[str, Form()] = "",
    nome: Annotated[str, Form()] = "", site_url: Annotated[str, Form()] = "",
    cor_primaria: Annotated[str, Form()] = "", cor_destaque: Annotated[str, Form()] = "",
):  # fmt: skip
    _conferir(admin, csrf)
    try:
        central.editar(db, slug, nome, site_url, _cor(cor_primaria, COR_PRIMARIA),
                       _cor(cor_destaque, COR_DESTAQUE))  # fmt: skip
    except RegraNegocio as e:
        return _ir(f"/plataforma/{slug}", erro=e.mensagem)
    return _ir(f"/plataforma/{slug}", "salva")


@router.get("/{slug}/logo")
def ver_logo(slug: str, admin: Admin):
    logo = central.logo(_imobiliaria(slug))
    if logo is None:
        raise HTTPException(404)
    return Response(logo[0], media_type=logo[1], headers={"Cache-Control": "no-store"})


@router.post("/{slug}/logo")
def enviar_logo(slug: str, admin: Admin, logo: UploadFile, csrf: Annotated[str, Form()] = ""):
    _conferir(admin, csrf)
    try:
        central.definir_logo(_imobiliaria(slug), logo.file.read(central.LOGO_MAX + 1))
    except RegraNegocio as e:
        return _ir(f"/plataforma/{slug}", erro=e.mensagem)
    return _ir(f"/plataforma/{slug}", "logo")


@router.post("/{slug}/logo/remover")
def remover_logo(slug: str, admin: Admin, csrf: Annotated[str, Form()] = ""):
    _conferir(admin, csrf)
    central.definir_logo(_imobiliaria(slug), None)
    return _ir(f"/plataforma/{slug}", "logo-removido")


@router.post("/{slug}/dominios")
def adicionar_dominio(slug: str, db: Db, admin: Admin, csrf: Annotated[str, Form()] = "",
                      dominio: Annotated[str, Form()] = ""):  # fmt: skip
    _conferir(admin, csrf)
    try:
        central.adicionar_dominio(db, slug, dominio)
    except RegraNegocio as e:
        return _ir(f"/plataforma/{slug}", erro=e.mensagem)
    return _ir(f"/plataforma/{slug}", "dominio")


@router.post("/{slug}/dominios/remover")
def remover_dominio(slug: str, db: Db, admin: Admin, csrf: Annotated[str, Form()] = "",
                    dominio: Annotated[str, Form()] = ""):  # fmt: skip
    _conferir(admin, csrf)
    central.remover_dominio(db, slug, dominio)
    return _ir(f"/plataforma/{slug}", "dominio-removido")


@router.post("/{slug}/situacao")
def situacao(slug: str, db: Db, admin: Admin, csrf: Annotated[str, Form()] = "",
             ativa: Annotated[str, Form()] = ""):  # fmt: skip
    _conferir(admin, csrf)
    central.definir_ativa(db, slug, ativa == "1")
    return _ir(f"/plataforma/{slug}", "ativada" if ativa == "1" else "desativada")


@router.post("/{slug}/administrador")
def administrador(
    slug: str, admin: Admin, csrf: Annotated[str, Form()] = "",
    nome: Annotated[str, Form()] = "", login: Annotated[str, Form()] = "",
    senha: Annotated[str, Form()] = "",
):  # fmt: skip
    """Cria o administrador da imobiliária ou redefine a senha dele."""
    from app.modules.equipe.services import criar_administrador

    _conferir(admin, csrf)
    imob = _imobiliaria(slug)
    try:
        with usar(imob), fabrica(imob)() as db:
            criar_administrador(db, nome or login, login, senha)
    except RegraNegocio as e:
        return _ir(f"/plataforma/{slug}", erro=e.mensagem)
    return _ir(f"/plataforma/{slug}", "admin")

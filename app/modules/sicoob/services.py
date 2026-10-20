"""Regras da integração Sicoob: configuração, boletos (Cobrança Bancária v3),
cobranças Pix (Pix Recebimentos) e extrato/saldo (Conta Corrente)."""

import base64
import re
import uuid
from datetime import date, timedelta

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.errors import NaoEncontrado, RegraNegocio
from app.core.tempo import agora
from app.modules.crm.models import Contato
from app.modules.financeiro.models import ContaBancaria, LinhaExtrato
from app.modules.locacao import models as loc
from app.modules.locacao.enums import StatusCobranca
from app.modules.sicoob import retorno
from app.modules.sicoob import schemas as s
from app.modules.sicoob.cliente import ClienteSicoob
from app.modules.sicoob.models import BoletoSicoob, ChamadaSicoob, ConfiguracaoSicoob, PixSicoob


def _digitos(v: str | None) -> str:
    return re.sub(r"\D", "", v or "")


def _numero(v: str, campo: str) -> int:
    d = _digitos(v)
    if not d:
        raise RegraNegocio(f"Informe o {campo} em Configuração.")
    return int(d)


# ------------------------------------------------------------- Configuração


def _registro(db: Session) -> ConfiguracaoSicoob:
    r = db.get(ConfiguracaoSicoob, 1)
    if r is None:
        r = ConfiguracaoSicoob(id=1, dados={}, token_sandbox="")
        db.add(r)
        db.flush()
    return r


def configuracao(db: Session) -> s.ConfiguracaoSaida:
    r = _registro(db)
    return s.ConfiguracaoSaida.model_validate(r.dados or {}).model_copy(
        update={"token_configurado": bool(r.token_sandbox)}
    )


def salvar_configuracao(db: Session, e: s.ConfiguracaoEntrada) -> s.ConfiguracaoSaida:
    if e.conta_bancaria_id and db.get(ContaBancaria, e.conta_bancaria_id) is None:
        raise RegraNegocio("Conta bancária não encontrada.")
    r = _registro(db)
    r.dados = s.Configuracao.model_validate(e.model_dump()).model_dump()
    if e.token is not None and e.token.strip():
        r.token_sandbox = e.token.strip()
    db.commit()
    return configuracao(db)


def cliente(db: Session, usuario_id: str | None = None) -> tuple[ClienteSicoob, s.Configuracao]:
    r = _registro(db)
    cfg = s.Configuracao.model_validate(r.dados or {})
    return ClienteSicoob(db, cfg.ambiente, cfg.client_id, r.token_sandbox, usuario_id), cfg


def testar(db: Session, usuario_id: str | None) -> list[s.ResultadoTeste]:
    """Uma chamada simples em cada API. 2xx = ok; 401/403 = credencial
    recusada; outros 4xx = a API respondeu (falta algum dado)."""
    cli, cfg = cliente(db, usuario_id)
    hoje = agora()
    testes = [
        ("cobranca", "Cobrança Bancária", "/boletos", {"numeroCliente": _digitos(cfg.numero_cliente) or "0",
         "codigoModalidade": cfg.codigo_modalidade, "nossoNumero": "1"}),  # fmt: skip
        ("pix", "Pix Recebimentos", "/cob", {"inicio": f"{(hoje - timedelta(days=1)).date()}T00:00:00-03:00",
         "fim": f"{hoje.date()}T23:59:59-03:00"}),  # fmt: skip
        ("conta", "Conta Corrente", "/v4/saldo", {"numeroContaCorrente": _digitos(cfg.numero_conta_corrente) or "0"}),
    ]
    resultado = []
    for api, nome, caminho, params in testes:
        try:
            status, _ = cli.chamar(api, "GET", caminho, f"Testar {nome}", params=params,
                                   aceitar=tuple(range(400, 500)))  # fmt: skip
            if 200 <= status < 300:
                ok, msg = True, "Conectado e autorizado."
            elif status in (401, 403):
                ok, msg = False, "Credenciais recusadas (client_id ou token)."
            else:
                ok, msg = True, f"API respondeu (HTTP {status}); a autenticação passou."
        except RegraNegocio as e:
            ok, status, msg = False, None, e.mensagem
        resultado.append(s.ResultadoTeste(api=api, nome=nome, ok=ok, status_http=status, mensagem=msg))
    return resultado


# ---------------------------------------------------------------- Boletos


def _saida_boleto(b: BoletoSicoob) -> s.BoletoSaida:
    return s.BoletoSaida.model_validate(b, from_attributes=True)


def boletos(db: Session) -> list[s.BoletoSaida]:
    return [_saida_boleto(b) for b in db.scalars(
        sa.select(BoletoSicoob).order_by(BoletoSicoob.criado_em.desc()).limit(200))]  # fmt: skip


def _cobranca_total(c: loc.Cobranca) -> float:
    return round(sum(i.valor for i in c.itens) + c.multa + c.juros - c.desconto, 2)


def cobrancas_abertas(db: Session) -> list[s.CobrancaAberta]:
    lista = []
    for c in db.scalars(sa.select(loc.Cobranca).where(loc.Cobranca.status == StatusCobranca.aberta)
                        .order_by(loc.Cobranca.vencimento).limit(300)):  # fmt: skip
        contrato = db.get(loc.ContratoLocacao, c.contrato_id)
        inquilino = db.get(Contato, contrato.locatario_id) if contrato else None
        lista.append(s.CobrancaAberta(
            id=c.id, descricao=f"{contrato.numero if contrato else ''} · {c.competencia.strftime('%m/%Y')}",
            locatario=inquilino.nome if inquilino else "", valor=_cobranca_total(c), vencimento=c.vencimento,
        ))  # fmt: skip
    return lista


def rascunho(db: Session, cobranca_id: str) -> s.Rascunho:
    """Preenche o boleto/Pix com a cobrança do aluguel (valor, vencimento e
    o locatário como pagador)."""
    c = db.get(loc.Cobranca, cobranca_id)
    if c is None:
        raise NaoEncontrado("Cobrança não encontrada.")
    contrato = db.get(loc.ContratoLocacao, c.contrato_id)
    p = db.get(Contato, contrato.locatario_id)
    endereco = ", ".join(x for x in (p.logradouro, p.numero, p.complemento) if x)
    return s.Rascunho(
        valor=_cobranca_total(c), vencimento=c.vencimento,
        descricao=f"Aluguel {contrato.numero} {c.competencia.strftime('%m/%Y')}",
        multa_percentual=contrato.multa_atraso, juros_mes_percentual=contrato.juros_mes,
        pagador=s.Pagador(documento=_digitos(p.documento), nome=p.nome, endereco=endereco,
                          bairro=p.bairro, cidade=p.cidade, cep=_digitos(p.cep), uf=p.uf, email=p.email),
    )  # fmt: skip


def corpo_boleto(cfg: s.Configuracao, e: s.BoletoEntrada, hoje: date) -> dict:
    """Corpo do POST /boletos (Cobrança Bancária v3)."""
    doc = _digitos(e.pagador.documento)
    if len(doc) not in (11, 14):
        raise RegraNegocio("CPF/CNPJ do pagador inválido.")
    if e.vencimento < hoje:
        raise RegraNegocio("O vencimento não pode ser no passado.")
    depois = (e.vencimento + timedelta(days=1)).isoformat()
    corpo = {
        "numeroCliente": _numero(cfg.numero_cliente, "número do cliente (beneficiário)"),
        "codigoModalidade": cfg.codigo_modalidade,
        "numeroContaCorrente": _numero(cfg.numero_conta_corrente, "número da conta corrente"),
        "codigoEspecieDocumento": "DM",
        "dataEmissao": hoje.isoformat(),
        "seuNumero": e.seu_numero or str(int(agora().timestamp()))[-10:],
        "identificacaoEmissaoBoleto": 2,  # o cliente (imobiliária) emite
        "identificacaoDistribuicaoBoleto": 2,  # o cliente distribui
        "valor": round(e.valor, 2),
        "dataVencimento": e.vencimento.isoformat(),
        "tipoDesconto": 0,
        "tipoMulta": 2 if e.multa_percentual else 0,  # 2 = percentual
        "tipoJurosMora": 2 if e.juros_mes_percentual else 3,  # 2 = taxa mensal; 3 = isento
        "numeroParcela": 1,
        "pagador": {
            "numeroCpfCnpj": doc, "nome": e.pagador.nome[:50], "endereco": e.pagador.endereco[:40],
            "bairro": e.pagador.bairro[:30], "cidade": e.pagador.cidade[:40], "cep": _digitos(e.pagador.cep),
            "uf": e.pagador.uf.upper(), "email": e.pagador.email,
        },
        "gerarPdf": True,
        "codigoCadastrarPIX": 1 if e.com_pix else 2,
    }  # fmt: skip
    if e.multa_percentual:
        corpo |= {"dataMulta": depois, "valorMulta": round(e.multa_percentual, 2)}
    if e.juros_mes_percentual:
        corpo |= {"dataJurosMora": depois, "valorJurosMora": round(e.juros_mes_percentual, 2)}
    if e.mensagem:
        corpo["mensagensInstrucao"] = [e.mensagem]
    return corpo


def registrar_boleto(db: Session, e: s.BoletoEntrada, usuario_id: str | None) -> tuple[s.BoletoSaida, str]:
    """Registra no Sicoob. Devolve o boleto e o PDF (base64) quando vier."""
    if e.cobranca_id and db.get(loc.Cobranca, e.cobranca_id) is None:
        raise RegraNegocio("Cobrança não encontrada.")
    cli, cfg = cliente(db, usuario_id)
    _, dados = cli.chamar("cobranca", "POST", "/boletos", "Registrar boleto",
                          corpo=corpo_boleto(cfg, e, agora().date()))  # fmt: skip
    r = (dados or {}).get("resultado") or {}
    if not r.get("nossoNumero"):
        raise RegraNegocio("O Sicoob não devolveu o nosso número do boleto.")
    b = BoletoSicoob(
        ambiente=cfg.ambiente, nosso_numero=str(r["nossoNumero"]), seu_numero=str(r.get("seuNumero") or ""),
        valor=float(r.get("valor") or e.valor), vencimento=e.vencimento,
        pagador_nome=e.pagador.nome, pagador_documento=_digitos(e.pagador.documento),
        linha_digitavel=r.get("linhaDigitavel") or "", codigo_barras=r.get("codigoBarras") or "",
        situacao=r.get("situacaoBoleto") or "Em Aberto", cobranca_id=e.cobranca_id,
    )  # fmt: skip
    db.add(b)
    db.commit()
    return _saida_boleto(b), r.get("pdfBoleto") or ""


def _boleto(db: Session, id: str) -> BoletoSicoob:
    b = db.get(BoletoSicoob, id)
    if b is None:
        raise NaoEncontrado("Boleto não encontrado.")
    return b


def consultar_boleto(db: Session, id: str, usuario_id: str | None) -> s.BoletoSaida:
    b = _boleto(db, id)
    cli, cfg = cliente(db, usuario_id)
    _, dados = cli.chamar("cobranca", "GET", "/boletos", "Consultar boleto", params={
        "numeroCliente": _numero(cfg.numero_cliente, "número do cliente"),
        "codigoModalidade": cfg.codigo_modalidade, "nossoNumero": b.nosso_numero})  # fmt: skip
    r = (dados or {}).get("resultado") or {}
    b.situacao = r.get("situacaoBoleto") or b.situacao
    b.linha_digitavel = r.get("linhaDigitavel") or b.linha_digitavel
    b.codigo_barras = r.get("codigoBarras") or b.codigo_barras
    db.commit()
    return _saida_boleto(b)


def pdf_boleto(db: Session, id: str, usuario_id: str | None) -> bytes:
    """Segunda via em PDF."""
    b = _boleto(db, id)
    cli, cfg = cliente(db, usuario_id)
    _, dados = cli.chamar("cobranca", "GET", "/boletos/segunda-via", "Segunda via (PDF)", params={
        "numeroCliente": _numero(cfg.numero_cliente, "número do cliente"),
        "codigoModalidade": cfg.codigo_modalidade, "nossoNumero": b.nosso_numero, "gerarPdf": "true"})  # fmt: skip
    pdf = ((dados or {}).get("resultado") or {}).get("pdfBoleto")
    if not pdf:
        raise RegraNegocio("O Sicoob não devolveu o PDF deste boleto.")
    try:
        return base64.b64decode(pdf)
    except ValueError as e:
        raise RegraNegocio("PDF do boleto inválido.") from e


def baixar_boleto(db: Session, id: str, usuario_id: str | None) -> s.BoletoSaida:
    """Pede a baixa (cancelamento) do boleto no banco."""
    b = _boleto(db, id)
    cli, cfg = cliente(db, usuario_id)
    cli.chamar("cobranca", "POST", f"/boletos/{b.nosso_numero}/baixar", "Baixar boleto", corpo={
        "numeroCliente": _numero(cfg.numero_cliente, "número do cliente"),
        "codigoModalidade": cfg.codigo_modalidade})  # fmt: skip
    b.situacao = "Baixado"
    db.commit()
    return _saida_boleto(b)


# -------------------------------------------------------------------- Pix


def qr_png(texto: str) -> str:
    if not texto:
        return ""
    import io

    import segno

    saida = io.BytesIO()
    segno.make(texto, error="m").save(saida, kind="png", scale=6, border=2)
    return "data:image/png;base64," + base64.b64encode(saida.getvalue()).decode()


def _saida_pix(p: PixSicoob, com_qr: bool = False) -> s.PixSaida:
    out = s.PixSaida.model_validate(p, from_attributes=True)
    return out.model_copy(update={"qr_code_png": qr_png(p.copia_e_cola)}) if com_qr else out


def cobrancas_pix(db: Session) -> list[s.PixSaida]:
    return [_saida_pix(p) for p in db.scalars(
        sa.select(PixSicoob).order_by(PixSicoob.criado_em.desc()).limit(200))]  # fmt: skip


def criar_pix(db: Session, e: s.PixEntrada, usuario_id: str | None) -> s.PixSaida:
    cli, cfg = cliente(db, usuario_id)
    if not cfg.chave_pix.strip():
        raise RegraNegocio("Informe a chave Pix da imobiliária em Configuração.")
    corpo: dict = {
        "calendario": {"expiracao": e.expiracao_horas * 3600},
        "valor": {"original": f"{e.valor:.2f}"},
        "chave": cfg.chave_pix.strip(),
    }
    doc = _digitos(e.devedor_documento)
    if doc:
        if len(doc) not in (11, 14) or not e.devedor_nome.strip():
            raise RegraNegocio("Informe CPF/CNPJ válido e o nome do pagador (ou deixe os dois em branco).")
        corpo["devedor"] = {"cpf" if len(doc) == 11 else "cnpj": doc, "nome": e.devedor_nome.strip()[:200]}
    if e.descricao.strip():
        corpo["solicitacaoPagador"] = e.descricao.strip()[:140]
    txid = uuid.uuid4().hex + uuid.uuid4().hex[:3]  # 35 caracteres (26 a 35 aceitos)
    _, dados = cli.chamar("pix", "PUT", f"/cob/{txid}", "Criar cobrança Pix", corpo=corpo)
    dados = dados or {}
    p = PixSicoob(
        ambiente=cfg.ambiente, txid=dados.get("txid") or txid, valor=e.valor,
        devedor_nome=e.devedor_nome.strip(), devedor_documento=doc, descricao=e.descricao.strip(),
        status=dados.get("status") or "ATIVA",
        copia_e_cola=dados.get("pixCopiaECola") or dados.get("brcode") or "",
        location=dados.get("location") or (dados.get("loc") or {}).get("location") or "",
        cobranca_id=e.cobranca_id,
    )  # fmt: skip
    db.add(p)
    db.commit()
    return _saida_pix(p, com_qr=True)


def consultar_pix(db: Session, id: str, usuario_id: str | None) -> s.PixSaida:
    p = db.get(PixSicoob, id)
    if p is None:
        raise NaoEncontrado("Cobrança Pix não encontrada.")
    cli, _ = cliente(db, usuario_id)
    _, dados = cli.chamar("pix", "GET", f"/cob/{p.txid}", "Consultar cobrança Pix")
    dados = dados or {}
    p.status = dados.get("status") or p.status
    p.copia_e_cola = dados.get("pixCopiaECola") or dados.get("brcode") or p.copia_e_cola
    db.commit()
    return _saida_pix(p, com_qr=True)


def pix_recebidos(db: Session, inicio: date, fim: date, usuario_id: str | None) -> list[s.PixRecebido]:
    if fim < inicio or (fim - inicio).days > 31:
        raise RegraNegocio("Escolha um período de até 31 dias.")
    cli, _ = cliente(db, usuario_id)
    _, dados = cli.chamar("pix", "GET", "/pix", "Pix recebidos", params={
        "inicio": f"{inicio}T00:00:00-03:00", "fim": f"{fim}T23:59:59-03:00"})  # fmt: skip
    return [
        s.PixRecebido(
            end_to_end_id=x.get("endToEndId", ""), txid=x.get("txid") or "", valor=float(x.get("valor") or 0),
            horario=x.get("horario", ""), pagador=(x.get("pagador") or {}).get("nome", "") if isinstance(x.get("pagador"), dict) else "",
            info=x.get("infoPagador") or "",
        )  # fmt: skip
        for x in (dados or {}).get("pix", [])
    ]


# ---------------------------------------------------------- Conta corrente


def _f(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def saldo(db: Session, usuario_id: str | None) -> s.Saldo:
    cli, cfg = cliente(db, usuario_id)
    _, dados = cli.chamar("conta", "GET", "/v4/saldo", "Saldo", params={
        "numeroContaCorrente": _numero(cfg.numero_conta_corrente, "número da conta corrente")})  # fmt: skip
    r = (dados or {}).get("resultado") or {}
    return s.Saldo(saldo=_f(r.get("saldo")), saldo_limite=_f(r.get("saldoLimite")),
                   saldo_bloqueado=_f(r.get("saldoBloqueado")))  # fmt: skip


def extrato(db: Session, mes: int, ano: int, usuario_id: str | None) -> s.Extrato:
    cli, cfg = cliente(db, usuario_id)
    _, dados = cli.chamar("conta", "GET", f"/v4/extrato/{mes}/{ano}", "Extrato", params={
        "numeroContaCorrente": _numero(cfg.numero_conta_corrente, "número da conta corrente")})  # fmt: skip
    r = (dados or {}).get("resultado") or {}
    transacoes = []
    for t in r.get("transacoes") or []:
        try:
            dia = date.fromisoformat(str(t.get("data") or t.get("dataLote"))[:10])
        except ValueError:
            continue
        transacoes.append(s.Transacao(
            tipo=str(t.get("tipo") or ""), valor=_f(t.get("valor")), data=dia,
            descricao=str(t.get("descricao") or ""), documento=str(t.get("numeroDocumento") or ""),
            complemento=str(t.get("descInfComplementar") or ""),
        ))  # fmt: skip
    return s.Extrato(saldo_anterior=_f(r.get("saldoAnterior")), saldo_atual=_f(r.get("saldoAtual")),
                     transacoes=transacoes)  # fmt: skip


def importar_extrato(db: Session, mes: int, ano: int, usuario_id: str | None) -> s.ResultadoImportacao:
    """Leva as transações do mês para a Conciliação bancária (conta escolhida
    em Configuração). Linhas iguais já importadas são ignoradas."""
    _, cfg = cliente(db, usuario_id)
    if not cfg.conta_bancaria_id or db.get(ContaBancaria, cfg.conta_bancaria_id) is None:
        raise RegraNegocio("Escolha em Configuração a conta do Financeiro que recebe o extrato.")
    e = extrato(db, mes, ano, usuario_id)
    novas = repetidas = 0
    for t in e.transacoes:
        valor = round(t.valor if t.tipo.upper().startswith("C") else -abs(t.valor), 2)
        descricao = (t.descricao + (f" – {t.complemento}" if t.complemento else ""))[:200]
        existe = db.scalar(sa.select(LinhaExtrato.id).where(
            LinhaExtrato.conta_id == cfg.conta_bancaria_id, LinhaExtrato.data == t.data,
            LinhaExtrato.valor == valor, LinhaExtrato.descricao == descricao,
            LinhaExtrato.documento == t.documento[:50]).limit(1))  # fmt: skip
        if existe:
            repetidas += 1
            continue
        db.add(LinhaExtrato(conta_id=cfg.conta_bancaria_id, data=t.data, descricao=descricao,
                            valor=valor, documento=t.documento[:50]))  # fmt: skip
        novas += 1
    db.commit()
    return s.ResultadoImportacao(importadas=novas, repetidas=repetidas)


# ---------------------------------------------------------------- Registro


def chamadas(db: Session, limite: int = 100) -> list[ChamadaSicoob]:
    return list(db.scalars(sa.select(ChamadaSicoob).order_by(ChamadaSicoob.criado_em.desc()).limit(limite)))


# ------------------------------------------------------- Retorno (CNAB 240)


def _boleto_do_retorno(db: Session, p: retorno.Pagamento) -> BoletoSicoob | None:
    """Acha o boleto pelo nosso número (com ou sem o dígito verificador no
    fim) e, se não achar, pelo seu número."""
    candidatos = [p.nosso_numero]
    if len(p.nosso_numero) > 1:
        candidatos.append(p.nosso_numero[:-1])
    for nn in candidatos:
        if not nn:
            continue
        b = db.scalar(sa.select(BoletoSicoob).where(sa.func.trim(BoletoSicoob.nosso_numero) == nn)
                      .order_by(BoletoSicoob.criado_em.desc()))  # fmt: skip
        if b is not None:
            return b
    if p.seu_numero:
        return db.scalar(sa.select(BoletoSicoob).where(BoletoSicoob.seu_numero == p.seu_numero)
                         .order_by(BoletoSicoob.criado_em.desc()))  # fmt: skip
    return None


def processar_retorno(db: Session, e: s.RetornoEntrada) -> s.ResultadoRetorno:
    """Lê o retorno do Sicoob e dá baixa nas cobranças do aluguel pagas.
    Com `aplicar=False` só mostra o que seria feito."""
    try:
        raw = base64.b64decode(e.conteudo, validate=True)
    except ValueError as ex:
        raise RegraNegocio("Não foi possível ler o arquivo enviado.") from ex
    arq = retorno.ler(raw)
    itens, baixas = [], 0
    for p in arq.pagamentos:
        item = s.ItemRetorno(linha=p.linha, nosso_numero=p.nosso_numero, seu_numero=p.seu_numero,
                             movimento=p.movimento, valor_pago=p.valor_pago, data_credito=p.data_credito,
                             situacao="ignorado", mensagem="")  # fmt: skip
        itens.append(item)
        if p.movimento not in retorno.LIQUIDACAO:
            item.mensagem = retorno.OUTROS.get(p.movimento, f"Movimento {p.movimento}") + " (sem pagamento)."
            continue
        b = _boleto_do_retorno(db, p)
        if b is None:
            item.situacao, item.mensagem = "sem_boleto", "Boleto não emitido pelo sistema; dê baixa à mão."
            continue
        c = db.get(loc.Cobranca, b.cobranca_id) if b.cobranca_id else None
        if c is None:
            item.situacao, item.mensagem = "sem_cobranca", "Boleto avulso, sem cobrança do aluguel vinculada."
            if e.aplicar:
                b.situacao = "Liquidado"
            continue
        contrato = db.get(loc.ContratoLocacao, c.contrato_id)
        inquilino = db.get(Contato, contrato.locatario_id) if contrato else None
        item.cobranca_id = c.id
        item.descricao = f"{contrato.numero if contrato else ''} · {c.competencia.strftime('%m/%Y')}"
        item.locatario = inquilino.nome if inquilino else ""
        if c.status == StatusCobranca.paga:
            item.situacao, item.mensagem = "ja_paga", "A cobrança já estava paga."
            continue
        if c.status == StatusCobranca.cancelada:
            item.situacao, item.mensagem = "divergente", "A cobrança está cancelada; confira."
            continue
        total = _cobranca_total(c)
        if p.valor_pago + 0.009 < total:
            item.situacao = "divergente"
            item.mensagem = f"Pago R$ {p.valor_pago:.2f}, menor que a cobrança (R$ {total:.2f}); dê baixa à mão."
            continue
        item.situacao = "aplicada" if e.aplicar else "baixar"
        item.mensagem = "Baixa feita." if e.aplicar else "Será marcada como paga."
        baixas += 1
        if e.aplicar:
            c.status = StatusCobranca.paga
            c.data_pagamento = p.data_credito or agora().date()
            c.valor_pago = p.valor_pago
            b.situacao = "Liquidado"
    if e.aplicar:
        db.commit()
    return s.ResultadoRetorno(arquivo_linhas=arq.linhas, aplicado=e.aplicar, itens=itens, baixas=baixas)

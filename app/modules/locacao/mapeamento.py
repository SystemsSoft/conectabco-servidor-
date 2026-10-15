"""Conversão entre tabelas e schemas da locação."""

from app.modules.locacao import models as m
from app.modules.locacao import schemas as s


def _colunas(obj, modelo) -> dict:
    return {c.key: getattr(obj, c.key) for c in modelo.__mapper__.columns}


def aplicar_contrato(c: m.ContratoLocacao, e: s.ContratoEntrada) -> None:
    for campo, valor in e.model_dump(exclude={"beneficiarios"}).items():
        setattr(c, campo, valor)
    c.beneficiarios = [
        m.Beneficiario(ordem=i, contato_id=b.contato_id, percentual=b.percentual)
        for i, b in enumerate(e.beneficiarios)
    ]


def contrato_saida(c: m.ContratoLocacao) -> s.ContratoSaida:
    return s.ContratoSaida.model_validate(
        {
            **_colunas(c, m.ContratoLocacao),
            "beneficiarios": [
                {"contato_id": b.contato_id, "percentual": b.percentual}
                for b in c.beneficiarios
            ],
        }
    )


def aplicar_despesa(d: m.Despesa, e: s.DespesaEntrada) -> None:
    for campo, valor in e.model_dump().items():
        setattr(d, campo, valor)


def despesa_saida(d: m.Despesa) -> s.DespesaSaida:
    return s.DespesaSaida.model_validate(d)


def aplicar_cobranca(c: m.Cobranca, e: s.CobrancaEntrada) -> None:
    for campo, valor in e.model_dump(exclude={"itens"}).items():
        setattr(c, campo, valor)
    c.itens = [
        m.ItemCobranca(ordem=i, descricao=it.descricao, valor=it.valor, tipo=it.tipo)
        for i, it in enumerate(e.itens)
    ]


def cobranca_saida(c: m.Cobranca) -> s.CobrancaSaida:
    return s.CobrancaSaida.model_validate(
        {
            **_colunas(c, m.Cobranca),
            "itens": [
                {"descricao": i.descricao, "valor": i.valor, "tipo": i.tipo}
                for i in c.itens
            ],
        }
    )

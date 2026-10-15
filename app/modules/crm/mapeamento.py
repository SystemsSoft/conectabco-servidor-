"""Conversão entre as tabelas (models) e os contratos da API (schemas)."""

from app.modules.crm import models as m
from app.modules.crm import schemas as s


def _unicos[T](itens: list[T]) -> list[T]:
    return list(dict.fromkeys(itens))


def _na_ordem_do_enum[E](valores: list[E]) -> list[E]:
    """Conjuntos (papéis, finalidades) sempre na ordem de declaração do enum."""
    return sorted(valores, key=lambda v: list(type(v)).index(v))


def _campos(entrada: s.Esquema, excluir: set[str]) -> dict:
    return entrada.model_dump(exclude=excluir)


# ----------------------------------------------------------------- Imóveis

_FILHOS_IMOVEL = {"finalidades", "personalizadas", "anexos", "comodidades"}


def aplicar_imovel(imovel: m.Imovel, e: s.ImovelEntrada) -> None:
    for campo, valor in _campos(e, _FILHOS_IMOVEL).items():
        setattr(imovel, campo, valor)
    imovel.comodidades = _unicos([c.strip() for c in e.comodidades if c.strip()])
    imovel.finalidades = [
        m.ImovelFinalidade(finalidade=f) for f in _unicos(e.finalidades)
    ]
    imovel.personalizadas = [
        m.CaracteristicaPersonalizada(ordem=i, nome=c.nome.strip(), valor=c.valor)
        for i, c in enumerate(e.personalizadas)
        if c.nome.strip()
    ]
    imovel.anexos = [
        m.Anexo(ordem=i, tipo=a.tipo, titulo=a.titulo, url=a.url)
        for i, a in enumerate(e.anexos)
    ]


def imovel_saida(imovel: m.Imovel) -> s.ImovelSaida:
    return s.ImovelSaida.model_validate(
        {
            **{c.key: getattr(imovel, c.key) for c in m.Imovel.__mapper__.columns},
            "finalidades": _na_ordem_do_enum(
                [f.finalidade for f in imovel.finalidades]
            ),
            "personalizadas": [
                {"nome": c.nome, "valor": c.valor} for c in imovel.personalizadas
            ],
            "anexos": [
                {"tipo": a.tipo, "titulo": a.titulo, "url": a.url}
                for a in imovel.anexos
            ],
            "comodidades": imovel.comodidades or [],
        }
    )


# ---------------------------------------------------------------- Contatos


def aplicar_contato(contato: m.Contato, e: s.ContatoEntrada) -> None:
    for campo, valor in _campos(e, {"papeis", "perfil"}).items():
        setattr(contato, campo, valor)
    contato.papeis = [m.ContatoPapel(papel=p) for p in _unicos(e.papeis)]
    if e.perfil is None:
        contato.perfil = None
        return
    dados = e.perfil.model_dump()
    dados["tipos"] = [t.value for t in _unicos(e.perfil.tipos)]
    dados["comodidades"] = _unicos(
        [c.strip() for c in e.perfil.comodidades if c.strip()]
    )
    if contato.perfil is None:
        contato.perfil = m.PerfilInteresse(**dados)
    else:
        for campo, valor in dados.items():
            setattr(contato.perfil, campo, valor)


def contato_saida(contato: m.Contato) -> s.ContatoSaida:
    p = contato.perfil
    perfil = None
    if p is not None:
        perfil = {
            c.key: getattr(p, c.key)
            for c in m.PerfilInteresse.__mapper__.columns
            if c.key != "contato_id"
        }
    return s.ContatoSaida.model_validate(
        {
            **{c.key: getattr(contato, c.key) for c in m.Contato.__mapper__.columns},
            "papeis": _na_ordem_do_enum([p.papel for p in contato.papeis]),
            "perfil": perfil,
        }
    )


# ------------------------------------------------- Central de Relacionamento


def aplicar_evento(evento: m.Evento, e: s.EventoEntrada) -> None:
    for campo, valor in e.model_dump().items():
        setattr(evento, campo, valor)


def evento_saida(evento: m.Evento) -> s.EventoSaida:
    return s.EventoSaida.model_validate(evento)

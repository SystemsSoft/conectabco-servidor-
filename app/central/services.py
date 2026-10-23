"""Cadastro das imobiliárias e preparo do banco de cada uma (usado pelo
gerenciar.py e pelo cadastro em memória de app.core.imobiliarias)."""

import re
from collections.abc import Iterable
from pathlib import Path

import sqlalchemy as sa
from sqlalchemy import URL, make_url
from sqlalchemy.orm import Session

from app.central import models as m
from app.core.config import get_settings
from app.core.database import Base, BaseCentral, criar_engine, fabrica, motor, motor_central
from app.core.errors import NaoEncontrado, RegraNegocio
from app.core.imobiliarias import Imobiliaria, limpar_cadastro, normalizar_dominio
from app.core.tempo import agora

RAIZ = Path(__file__).resolve().parents[2]
_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")
_BANCO = re.compile(r"^[a-z0-9_]{1,64}$")
_DOMINIO = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)*$")


def sessao() -> Session:
    return Session(motor_central(), expire_on_commit=False)


def _para_contexto(r: m.Imobiliaria) -> Imobiliaria:
    return Imobiliaria(
        slug=r.slug,
        nome=r.nome,
        banco=r.banco,
        site_url=r.site_url,
        dominios=tuple(d.dominio for d in r.dominios),
        ativa=r.ativa,
    )


def carregar() -> list[Imobiliaria]:
    """Todas as imobiliárias, ativas ou não."""
    with sessao() as db:
        return [_para_contexto(r) for r in db.scalars(sa.select(m.Imobiliaria))]


def obter(db: Session, slug: str) -> m.Imobiliaria:
    r = db.get(m.Imobiliaria, slug.strip().lower())
    if r is None:
        raise NaoEncontrado(f"Imobiliária '{slug}' não cadastrada.")
    return r


# --------------------------------------------------------- Validações


def banco_padrao(slug: str) -> str:
    return "imob_" + slug.replace("-", "_")


def _validar_site(site_url: str) -> str:
    site_url = site_url.strip().rstrip("/")
    if site_url and not re.match(r"^https?://[^/\s]+$", site_url):
        raise RegraNegocio("Endereço do site inválido: use https://dominio (sem caminho).")
    return site_url


def _validar_dominio(db: Session, dominio: str, slug: str) -> str:
    dominio = normalizar_dominio(dominio)
    if len(dominio) > 253 or not _DOMINIO.match(dominio):
        raise RegraNegocio(f"Domínio inválido: {dominio or '(vazio)'}.")
    outro = db.get(m.Dominio, dominio)
    if outro and outro.imobiliaria_slug != slug:
        raise RegraNegocio(f"O domínio {dominio} já é da imobiliária '{outro.imobiliaria_slug}'.")
    return dominio


def validar_nova(
    db: Session, slug: str, nome: str, banco: str = "", site_url: str = "",
    dominios: Iterable[str] = (),
) -> Imobiliaria:  # fmt: skip
    """Confere os dados de uma imobiliária nova (sem gravar nada)."""
    slug = slug.strip().lower()
    if not _SLUG.match(slug):
        raise RegraNegocio(
            "Identificador inválido: use letras minúsculas, números e hífen (ex.: marcelo)."
        )
    if not nome.strip():
        raise RegraNegocio("Informe o nome da imobiliária.")
    banco = (banco or banco_padrao(slug)).strip()
    if not _BANCO.match(banco):
        raise RegraNegocio("Nome de banco inválido: use letras minúsculas, números e _.")
    if db.get(m.Imobiliaria, slug):
        raise RegraNegocio(f"Já existe uma imobiliária com o identificador '{slug}'.")
    if db.scalar(sa.select(m.Imobiliaria.slug).where(m.Imobiliaria.banco == banco)):
        raise RegraNegocio(f"O banco {banco} já é de outra imobiliária.")
    dominios = tuple(dict.fromkeys(_validar_dominio(db, d, slug) for d in dominios))
    site_url = _validar_site(site_url) or (f"https://{dominios[0]}" if dominios else "")
    return Imobiliaria(slug, nome.strip(), banco, site_url, dominios)


def registrar(db: Session, imob: Imobiliaria) -> None:
    r = m.Imobiliaria(slug=imob.slug, nome=imob.nome, banco=imob.banco,
                      site_url=imob.site_url, ativa=True, criada_em=agora())  # fmt: skip
    r.dominios = [m.Dominio(dominio=d) for d in imob.dominios]
    db.add(r)
    db.commit()
    limpar_cadastro()


# ------------------------------------------------- Bancos e migrações


def url_servidor(url: URL) -> URL:
    """A URL sem o banco (para criá-lo); `set(database=None)` não o tira."""
    return url._replace(database=None)


def _criar_banco(url: str | URL) -> bool:
    """CREATE DATABASE no MySQL (o SQLite cria o arquivo sozinho). Devolve
    False se o banco já existia."""
    url = make_url(url)
    if url.get_backend_name() == "sqlite":
        return url.database in (None, "", ":memory:") or not Path(url.database).exists()
    if url.get_backend_name() != "mysql":
        return True
    if not _BANCO.match(url.database or ""):
        raise RegraNegocio(f"Nome de banco inválido: {url.database}.")
    servidor = criar_engine(url_servidor(url))
    try:
        with servidor.connect() as c:
            existe = c.scalar(
                sa.text("SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name = :b"),
                {"b": url.database},
            )
            if not existe:
                c.execute(sa.text(
                    f"CREATE DATABASE `{url.database}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
                ))  # fmt: skip
            return not existe
    finally:
        servidor.dispose()


def _alembic(secao: str, engine: sa.Engine, comando: str = "upgrade") -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(RAIZ / "alembic.ini"), ini_section=secao)
    with engine.begin() as conexao:
        cfg.attributes["connection"] = conexao
        getattr(command, comando)(cfg, "head")


def _migrar(secao: str, engine: sa.Engine, metadata: sa.MetaData) -> None:
    """alembic upgrade head. No SQLite (desenvolvimento), que não roda as
    migrações feitas para o MySQL, o banco vazio nasce direto dos models, já
    marcado com a última versão."""
    if engine.dialect.name == "sqlite" and not sa.inspect(engine).get_table_names():
        metadata.create_all(engine)
        _alembic(secao, engine, "stamp")
    else:
        _alembic(secao, engine)


def migrar_central() -> None:
    """Cria o banco central, se preciso, e aplica as migrações dele."""
    _criar_banco(get_settings().url_central)
    _migrar("central", motor_central(), BaseCentral.metadata)


def migrar(imob: Imobiliaria) -> None:
    """Aplica as migrações no banco da imobiliária."""
    from app.modules import carregar_models

    carregar_models()
    _migrar("alembic", motor(imob), Base.metadata)


def criar_imobiliaria(
    slug: str, nome: str, banco: str = "", site_url: str = "",
    dominios: Iterable[str] = (), existente: bool = False,
) -> Imobiliaria:  # fmt: skip
    """Cadastra a imobiliária e prepara o banco dela (novo ou, com
    `existente`, um banco que já tem dados, como o da primeira imobiliária)."""
    from app.modules.personalizacao.models import DadosEmpresa

    migrar_central()
    with sessao() as db:
        imob = validar_nova(db, slug, nome, banco, site_url, dominios)
    criado = _criar_banco(get_settings().url_imobiliaria(imob.banco))
    if not criado and not existente:
        raise RegraNegocio(
            f"O banco {imob.banco} já existe. Para cadastrar um banco que já tem "
            "dados, use --existente."
        )
    migrar(imob)
    with fabrica(imob)() as db:
        if db.get(DadosEmpresa, 1) is None:
            db.add(DadosEmpresa(id=1, nome=imob.nome))
            db.commit()
    imob.pasta_arquivos.mkdir(parents=True, exist_ok=True)
    with sessao() as db:
        registrar(db, imob)
    return imob


# ------------------------------------------------------------ Edição


def editar(db: Session, slug: str, nome: str | None = None, site_url: str | None = None) -> None:
    r = obter(db, slug)
    if nome is not None:
        if not nome.strip():
            raise RegraNegocio("Informe o nome da imobiliária.")
        r.nome = nome.strip()
    if site_url is not None:
        r.site_url = _validar_site(site_url)
    db.commit()
    limpar_cadastro()


def adicionar_dominio(db: Session, slug: str, dominio: str) -> str:
    r = obter(db, slug)
    dominio = _validar_dominio(db, dominio, r.slug)
    if dominio not in {d.dominio for d in r.dominios}:
        r.dominios.append(m.Dominio(dominio=dominio))
    db.commit()
    limpar_cadastro()
    return dominio


def remover_dominio(db: Session, slug: str, dominio: str) -> None:
    r = obter(db, slug)
    dominio = normalizar_dominio(dominio)
    r.dominios = [d for d in r.dominios if d.dominio != dominio]
    db.commit()
    limpar_cadastro()


def definir_ativa(db: Session, slug: str, ativa: bool) -> None:
    """Desativada, a imobiliária deixa de abrir (API, site e portais); os
    dados continuam no banco dela."""
    obter(db, slug).ativa = ativa
    db.commit()
    limpar_cadastro()

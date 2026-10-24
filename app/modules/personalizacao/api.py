import base64
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import Field
from sqlalchemy.orm import Session

from app.core.auth import UsuarioLogado, exigir_modulo
from app.core.database import get_db
from app.core.documentos import validar_cpf_cnpj
from app.core.errors import NaoEncontrado, RegraNegocio
from app.core.imobiliarias import atual, com_imobiliaria, origem
from app.core.schemas import Esquema
from app.core.tempo import agora
from app.modules.personalizacao.models import DadosEmpresa

router = APIRouter(prefix="/personalizacao", tags=["Personalização"])
# Sem login: o app mostra a marca da imobiliária já na tela de entrada.
marca = APIRouter(tags=["Personalização"])
Db = Annotated[Session, Depends(get_db)]
LOGO_MAX = 2 * 1024 * 1024


def Texto(n: int):  # noqa: N802
    return Annotated[str, Field(max_length=n)]


class Empresa(Esquema):
    nome: Texto(200)
    atividade: Texto(100) = ""
    creci: Texto(40) = ""
    documento: Texto(18) = Field("", description="CNPJ ou CPF")
    endereco: Texto(300) = ""
    telefone: Texto(40) = ""
    email: Texto(200) = ""
    site: Texto(200) = ""
    chave_pix: Texto(150) = ""


class EmpresaSaida(Empresa):
    tem_logo: bool = False
    logo_atualizado_em: datetime | None = None


class Logo(Esquema):
    tipo: str = Field(description="image/png ou image/jpeg")
    base64: str


def _registro(db: Session) -> DadosEmpresa | None:
    return db.get(DadosEmpresa, 1)


def _saida(d: DadosEmpresa | None) -> EmpresaSaida:
    if d is None:
        return EmpresaSaida(nome=atual().nome)
    return EmpresaSaida(
        **{k: getattr(d, k) for k in Empresa.model_fields},
        tem_logo=d.logo is not None,
        logo_atualizado_em=d.logo_atualizado_em,
    )


def _obter_ou_criar(db: Session) -> DadosEmpresa:
    d = _registro(db)
    if d is None:
        d = DadosEmpresa(id=1, nome=atual().nome)
        db.add(d)
    return d


@router.get("/empresa", response_model=EmpresaSaida)
def obter_empresa(db: Db, _: UsuarioLogado):
    """Dados da imobiliária (todos os logados: usados ao imprimir)."""
    return _saida(_registro(db))


@router.put("/empresa", response_model=EmpresaSaida,
            dependencies=[exigir_modulo("personalizacao")])  # fmt: skip
def salvar_empresa(dados: Empresa, db: Db):
    if not dados.nome.strip():
        raise RegraNegocio("Informe o nome da imobiliária.")
    if dados.documento and not validar_cpf_cnpj(dados.documento):
        raise RegraNegocio("CNPJ/CPF inválido.")
    d = _obter_ou_criar(db)
    for campo, valor in dados.model_dump().items():
        setattr(d, campo, valor.strip() if isinstance(valor, str) else valor)
    db.commit()
    return _saida(d)


@router.get("/logo", response_model=Logo)
def obter_logo(db: Db, _: UsuarioLogado):
    d = _registro(db)
    if d is None or d.logo is None:
        raise NaoEncontrado("Sem logotipo personalizado.")
    return Logo(tipo=d.logo_tipo, base64=base64.b64encode(d.logo).decode())


@router.put("/logo", response_model=EmpresaSaida,
            dependencies=[exigir_modulo("personalizacao")])  # fmt: skip
def salvar_logo(dados: Logo, db: Db, request: Request):
    try:
        conteudo = base64.b64decode(dados.base64, validate=True)
    except ValueError:
        raise RegraNegocio("Imagem inválida.") from None
    if len(conteudo) > LOGO_MAX:
        raise RegraNegocio("O logotipo deve ter no máximo 2 MB.")
    if conteudo.startswith(b"\x89PNG\r\n\x1a\n"):
        tipo = "image/png"
    elif conteudo.startswith(b"\xff\xd8\xff"):
        tipo = "image/jpeg"
    else:
        raise RegraNegocio("Use uma imagem PNG ou JPG.")
    d = _obter_ou_criar(db)
    d.logo, d.logo_tipo, d.logo_atualizado_em = conteudo, tipo, agora()
    db.commit()
    return _saida(d)


@router.delete("/logo", response_model=EmpresaSaida,
               dependencies=[exigir_modulo("personalizacao")])  # fmt: skip
def remover_logo(db: Db):
    """Volta ao logotipo padrão do sistema."""
    d = _registro(db)
    if d is not None:
        d.logo, d.logo_tipo, d.logo_atualizado_em = None, "", agora()
        db.commit()
    return _saida(d)


class Marca(Esquema):
    imobiliaria: str = Field(description="Identificador (vai no cabeçalho X-Imobiliaria)")
    origem: str = Field(description="Como foi identificada: dominio, cabecalho, parametro ou padrao")
    nome: str
    cor_primaria: str = Field(description="#rrggbb (topo, fundos escuros)")
    cor_destaque: str = Field(description="#rrggbb (botões e realces)")
    tem_logo: bool
    logo: str = Field(description="Caminho do logotipo (PNG/JPG)")


@marca.get("/marca", response_model=Marca)
def obter_marca(db: Db):
    """Nome, paleta e logotipo da imobiliária (cadastrados no painel da
    plataforma), para o app se vestir com a identidade dela."""
    from app.central.painel import COR_DESTAQUE, COR_PRIMARIA

    imob = atual()
    d = _registro(db)
    return Marca(
        imobiliaria=imob.slug,
        origem=origem(),
        nome=(d.nome if d else "") or imob.nome,
        cor_primaria=imob.cor_primaria or COR_PRIMARIA,
        cor_destaque=imob.cor_destaque or COR_DESTAQUE,
        tem_logo=bool(d and d.logo),
        logo=com_imobiliaria("/logo"),
    )

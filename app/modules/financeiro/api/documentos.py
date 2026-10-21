from typing import Annotated

from fastapi import APIRouter, Depends, Response, UploadFile

from app.core.auth import UsuarioLogado
from app.core.database import get_db
from app.modules.financeiro import schemas as s
from app.modules.financeiro.documentos import DocumentoService

router = APIRouter()
_t = ["Financeiro • Documentos"]
Documentos = Annotated[DocumentoService, Depends(lambda db=Depends(get_db): DocumentoService(db))]


@router.get("/pastas", tags=_t, response_model=list[s.PastaSaida])
def listar_pastas(svc: Documentos):
    return svc.listar_pastas()


@router.put("/pastas/{id}", tags=_t, response_model=s.PastaSaida)
def salvar_pasta(id: str, dados: s.PastaEntrada, svc: Documentos, response: Response):
    """Cria ou renomeia a pasta."""
    salvo, criado = svc.salvar_pasta(id, dados)
    if criado:
        response.status_code = 201
    return salvo


@router.delete("/pastas/{id}", tags=_t, status_code=204)
def remover_pasta(id: str, svc: Documentos) -> None:
    """Exclui a pasta com todos os documentos dela."""
    svc.remover_pasta(id)


@router.put("/pastas/{id}/compartilhamento", tags=_t, response_model=s.PastaSaida)
def compartilhar_pasta(id: str, dados: s.Compartilhamento, svc: Documentos):
    """Define quais inquilinos e proprietários veem a pasta na área deles
    do portal (lista vazia deixa a pasta só para a equipe)."""
    return svc.compartilhar(id, dados)


@router.get("/destinatarios", tags=_t, response_model=list[s.Destinatario])
def destinatarios(svc: Documentos):
    """Inquilinos e proprietários que podem receber pastas."""
    return svc.destinatarios()


@router.get("/pastas/{id}/documentos", tags=_t, response_model=list[s.DocumentoSaida])
def listar_documentos(id: str, svc: Documentos):
    return svc.listar(id)


@router.post("/pastas/{id}/documentos", tags=_t, response_model=s.DocumentoSaida, status_code=201)
def enviar_documento(id: str, arquivo: UploadFile, svc: Documentos, usuario: UsuarioLogado):
    """Envia um PDF, Word ou Excel (multipart) para a pasta. O nome do
    documento começa como o nome do arquivo, sem a extensão."""
    return svc.enviar(id, arquivo.file, arquivo.filename or "", usuario.id)


@router.put("/documentos/{id}", tags=_t, response_model=s.DocumentoSaida)
def salvar_documento(id: str, dados: s.DocumentoEntrada, svc: Documentos):
    """Renomeia e/ou move o documento para outra pasta."""
    return svc.salvar(id, dados)


@router.post("/documentos/{id}/duplicar", tags=_t, response_model=s.DocumentoSaida, status_code=201)
def duplicar_documento(id: str, svc: Documentos, usuario: UsuarioLogado):
    """Cria uma cópia na mesma pasta, com o sufixo "(cópia)" no nome."""
    return svc.duplicar(id, usuario.id)


@router.post("/documentos/{id}/arquivo", tags=_t, response_model=s.DocumentoSaida)
def substituir_arquivo(id: str, arquivo: UploadFile, svc: Documentos, usuario: UsuarioLogado):
    """Troca o arquivo do documento (o antigo é apagado)."""
    return svc.substituir(id, arquivo.file, arquivo.filename or "", usuario.id)


@router.delete("/documentos/{id}", tags=_t, status_code=204)
def remover_documento(id: str, svc: Documentos) -> None:
    svc.remover(id)

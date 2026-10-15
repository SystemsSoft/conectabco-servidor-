from fastapi import APIRouter

from app.modules.crm import enums
from app.modules.crm.catalogos import COMODIDADES_PADRAO, ESTADOS_BRASIL, ESTADOS_CIVIS

router = APIRouter(prefix="/catalogos", tags=["CRM • Catálogos"])


@router.get("")
def catalogos() -> dict:
    """Opções dos formulários (valor + rótulo) e listas padrão."""
    return {
        "finalidades": enums.Finalidade.opcoes(),
        "tiposImovel": enums.TipoImovel.opcoes(),
        "statusImovel": enums.StatusImovel.opcoes(),
        "mobiliado": enums.Mobiliado.opcoes(),
        "tiposAnexo": enums.AnexoTipo.opcoes(),
        "tiposPessoa": enums.TipoPessoa.opcoes(),
        "papeisContato": enums.PapelContato.opcoes(),
        "origensContato": enums.OrigemContato.opcoes(),
        "etapasFunil": enums.EtapaFunil.opcoes(),
        "tiposEvento": enums.TipoEvento.opcoes(),
        "prioridades": enums.Prioridade.opcoes(),
        "comodidadesPadrao": COMODIDADES_PADRAO,
        "estados": ESTADOS_BRASIL,
        "estadosCivis": ESTADOS_CIVIS,
    }

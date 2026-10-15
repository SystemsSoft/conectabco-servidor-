from fastapi import APIRouter

from app.modules.crm.api import catalogos, contatos, cruzamento, eventos, imoveis

router = APIRouter(prefix="/crm")
for _r in (imoveis, contatos, eventos, cruzamento, catalogos):
    router.include_router(_r.router)

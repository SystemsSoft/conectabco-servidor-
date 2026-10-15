from fastapi import APIRouter

from app.modules.locacao.api import cobrancas, contratos, despesas, repasses

router = APIRouter(prefix="/locacao")
for _r in (contratos, despesas, cobrancas, repasses):
    router.include_router(_r.router)

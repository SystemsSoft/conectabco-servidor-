import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.core.errors import NaoEncontrado, RegraNegocio, validar_id
from app.core.schemas import Pagina, pagina
from app.modules.crm.repositories import ImovelRepository
from app.modules.manutencao import models as m
from app.modules.manutencao import schemas as s
from app.modules.manutencao.enums import ContextoManutencao, StatusManutencao, TipoManutencao


def _saida(mt: m.Manutencao) -> s.ManutencaoSaida:
    return s.ManutencaoSaida.model_validate(
        {
            **{c.key: getattr(mt, c.key) for c in m.Manutencao.__mapper__.columns},
            "diario": [s.RegistroDiario.model_validate(r) for r in mt.diario],
        }
    )


class ManutencaoService:
    def __init__(self, db: Session):
        self.db = db
        self.imoveis = ImovelRepository(db)

    def listar(
        self,
        limite: int,
        deslocamento: int,
        contexto: ContextoManutencao | None = None,
        imovel_id: str | None = None,
        status: StatusManutencao | None = None,
    ) -> Pagina[s.ManutencaoSaida]:
        q = sa.select(m.Manutencao)
        if contexto:
            q = q.where(m.Manutencao.contexto == contexto)
        if imovel_id:
            q = q.where(m.Manutencao.imovel_id == imovel_id)
        if status:
            q = q.where(m.Manutencao.status == status)
        total = self.db.scalar(sa.select(sa.func.count()).select_from(q.subquery())) or 0
        itens = self.db.scalars(
            q.order_by(m.Manutencao.criado_em).limit(limite).offset(deslocamento)
        ).all()
        return pagina([_saida(i) for i in itens], total, limite, deslocamento)

    def obter(self, id: str) -> s.ManutencaoSaida:
        return _saida(self._buscar(id))

    def salvar(self, id: str, dados: s.ManutencaoEntrada) -> tuple[s.ManutencaoSaida, bool]:
        """Grava a pauta com todo o diário; cria se o id (UUID do app) é novo."""
        id = validar_id(id)
        self._validar(dados)
        mt = self.db.get(m.Manutencao, id)
        criado = mt is None
        if criado:
            mt = m.Manutencao(id=id)
            self.db.add(mt)
        for campo, valor in dados.model_dump(exclude={"diario"}).items():
            setattr(mt, campo, valor)
        existentes = {r.id: r for r in mt.diario}
        novos = []
        for r in dados.diario:
            registro = existentes.get(r.id) or m.RegistroDiario(id=validar_id(r.id))
            for campo, valor in r.model_dump(exclude={"id"}).items():
                setattr(registro, campo, valor)
            novos.append(registro)
        mt.diario = novos
        self.db.commit()
        return _saida(mt), criado

    def remover(self, id: str) -> None:
        self.db.delete(self._buscar(id))
        self.db.commit()

    def _buscar(self, id: str) -> m.Manutencao:
        mt = self.db.get(m.Manutencao, id)
        if mt is None:
            raise NaoEncontrado("Manutenção não encontrada.")
        return mt

    def _validar(self, d: s.ManutencaoEntrada) -> None:
        if not d.imovel_id:
            raise RegraNegocio("Selecione o imóvel.")
        if self.imoveis.obter(d.imovel_id) is None:
            raise RegraNegocio("Imóvel não encontrado.")
        if d.tipo == TipoManutencao.outros and not d.tipo_outro.strip():
            raise RegraNegocio("Informe qual o tipo de manutenção.")
        if not d.descricao.strip():
            raise RegraNegocio("Descreva a manutenção.")
        for r in d.diario:
            if not r.profissional.strip():
                raise RegraNegocio("Informe o profissional.")
            if not r.servico.strip():
                raise RegraNegocio("Informe o serviço a ser executado.")

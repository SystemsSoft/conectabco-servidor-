"""Cruzamento de perfil: compara o perfil de interesse dos contatos com os
imóveis disponíveis (mesma pontuação do front-end)."""

import unicodedata

from app.core.formatacao import decimal_para_texto, formatar_moeda
from app.modules.crm.enums import Finalidade, StatusImovel
from app.modules.crm.schemas import ContatoSaida, ImovelSaida, Sugestao

SCORE_MINIMO = 50


def _norm(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in sem_acento if not unicodedata.combining(c)).lower().strip()


def _valor_para(imovel: ImovelSaida, f: Finalidade) -> float | None:
    return {
        Finalidade.venda: imovel.valor_venda,
        Finalidade.locacao: imovel.valor_locacao,
        Finalidade.temporada: imovel.valor_temporada,
    }[f]


def avaliar(contato: ContatoSaida, imovel: ImovelSaida) -> Sugestao | None:
    """None quando o contato não tem perfil, o imóvel não está disponível
    ou a finalidade não bate."""
    p = contato.perfil
    if p is None or imovel.status != StatusImovel.disponivel:
        return None
    if p.finalidade not in imovel.finalidades:
        return None

    ganho = 0.0
    total = 0
    atende: list[str] = []
    nao_atende: list[str] = []

    def criterio(peso: int, ok: bool, sim: str, nao: str) -> None:
        nonlocal ganho, total
        total += peso
        if ok:
            ganho += peso
            atende.append(sim)
        else:
            nao_atende.append(nao)

    if p.tipos:
        rotulo = imovel.tipo.rotulo
        criterio(20, imovel.tipo in p.tipos, f"Tipo: {rotulo}", f"Tipo diferente ({rotulo})")

    if p.valor_min is not None or p.valor_max is not None:
        v = _valor_para(imovel, p.finalidade)
        ok = (
            v is not None
            and (p.valor_min is None or v >= p.valor_min)
            and (p.valor_max is None or v <= p.valor_max)
        )
        criterio(
            25,
            ok,
            f"Valor na faixa ({formatar_moeda(v)})",
            "Valor não informado"
            if v is None
            else f"Valor fora da faixa ({formatar_moeda(v)})",
        )

    if p.cidade.strip():
        criterio(
            10,
            _norm(imovel.cidade) == _norm(p.cidade),
            f"Cidade: {imovel.cidade}",
            f"Cidade diferente ({imovel.cidade})",
        )

    bairros = [_norm(b) for b in p.bairros.split(",") if b.strip()]
    if bairros:
        b = _norm(imovel.bairro)
        criterio(
            15,
            bool(b) and any(b in x or x in b for x in bairros),
            f"Bairro: {imovel.bairro}",
            f"Bairro diferente ({imovel.bairro})",
        )

    if p.quartos_min > 0:
        criterio(
            10,
            imovel.quartos >= p.quartos_min,
            f"{imovel.quartos} quarto(s)",
            f"Menos de {p.quartos_min} quarto(s)",
        )
    if p.suites_min > 0:
        criterio(
            5,
            imovel.suites >= p.suites_min,
            f"{imovel.suites} suíte(s)",
            f"Menos de {p.suites_min} suíte(s)",
        )
    if p.vagas_min > 0:
        criterio(
            10,
            imovel.vagas >= p.vagas_min,
            f"{imovel.vagas} vaga(s)",
            f"Menos de {p.vagas_min} vaga(s)",
        )
    if p.area_min is not None:
        area = imovel.area_util or imovel.area_total or 0
        criterio(
            5,
            area >= p.area_min,
            f"Área de {decimal_para_texto(area)} m²",
            f"Área menor que {decimal_para_texto(p.area_min)} m²",
        )

    if p.comodidades:
        tem = {_norm(c) for c in imovel.comodidades} | {
            _norm(c.nome) for c in imovel.personalizadas
        }
        achadas = sum(1 for c in p.comodidades if _norm(c) in tem)
        total += 10
        ganho += 10 * achadas / len(p.comodidades)
        texto = f"Comodidades: {achadas} de {len(p.comodidades)}"
        (atende if achadas == len(p.comodidades) else nao_atende).append(texto)

    # Mesmo arredondamento do Dart (.round(): metade para longe do zero).
    score = 100 if total == 0 else int(ganho * 100 / total + 0.5)
    return Sugestao(
        contato_id=contato.id,
        contato_nome=contato.nome,
        imovel_id=imovel.id,
        imovel_codigo=imovel.codigo,
        imovel_titulo=imovel.titulo,
        score=score,
        atende=atende,
        nao_atende=nao_atende,
    )


class SugerirNegocios:
    def para_contato(
        self, contato: ContatoSaida, imoveis: list[ImovelSaida]
    ) -> list[Sugestao]:
        return self._ordenar([avaliar(contato, i) for i in imoveis])

    def para_imovel(
        self, imovel: ImovelSaida, contatos: list[ContatoSaida]
    ) -> list[Sugestao]:
        return self._ordenar([avaliar(c, imovel) for c in contatos])

    def total(self, contatos: list[ContatoSaida], imoveis: list[ImovelSaida]) -> int:
        return sum(len(self.para_contato(c, imoveis)) for c in contatos)

    @staticmethod
    def _ordenar(lista: list[Sugestao | None]) -> list[Sugestao]:
        validas = [r for r in lista if r is not None and r.score >= SCORE_MINIMO]
        return sorted(validas, key=lambda r: r.score, reverse=True)

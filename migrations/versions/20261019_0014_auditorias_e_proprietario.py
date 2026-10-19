"""auditorias e área do proprietário

Revision ID: 0014
Revises: 0013
Create Date: 2026-10-19 12:00:00.000000

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0014'
down_revision: Union[str, Sequence[str], None] = '0013'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_AUDITORIAS = {
    'administrador': ['visualizar', 'criar', 'editar', 'excluir'],
    'gerente': ['visualizar', 'criar', 'editar', 'excluir'],
    'corretor': ['visualizar', 'criar', 'editar'],
}


def _enum(nome: str, valores: list[str]) -> sa.Enum:
    return sa.Enum(*valores, name=nome, native_enum=False, length=max(map(len, valores)) + 10)


def _indices(tabela: str, colunas: list[str]) -> None:
    for coluna in colunas:
        op.create_index(op.f(f'ix_{tabela}_{coluna}'), tabela, [coluna], unique=False)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('auditorias',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('numero', sa.String(length=20), nullable=False),
    sa.Column('imovel_id', sa.String(length=36), nullable=False),
    sa.Column('contrato_id', sa.String(length=36), nullable=True),
    sa.Column('proprietario_id', sa.String(length=36), nullable=True),
    sa.Column('corretor_id', sa.String(length=36), nullable=True),
    sa.Column('tipo', _enum('tipoauditoria', ['periodica', 'entrada', 'saida', 'extraordinaria']), nullable=False),
    sa.Column('status', _enum('statusauditoria', ['agendada', 'emAndamento', 'concluida', 'cancelada']), nullable=False),
    sa.Column('data_agendada', sa.Date(), nullable=True),
    sa.Column('data_realizada', sa.Date(), nullable=True),
    sa.Column('nota', sa.Integer(), nullable=True),
    sa.Column('resumo', sa.Text(), nullable=False),
    sa.Column('recomendacoes', sa.Text(), nullable=False),
    sa.Column('publicada', sa.Boolean(), nullable=False),
    sa.Column('concluida_em', sa.DateTime(), nullable=True),
    sa.Column('concluida_por_id', sa.String(length=36), nullable=True),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['contrato_id'], ['contratos_locacao.id'], name=op.f('fk_auditorias_contrato_id_contratos_locacao'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['corretor_id'], ['usuarios.id'], name=op.f('fk_auditorias_corretor_id_usuarios'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['imovel_id'], ['imoveis.id'], name=op.f('fk_auditorias_imovel_id_imoveis'), ondelete='RESTRICT'),
    sa.ForeignKeyConstraint(['proprietario_id'], ['contatos.id'], name=op.f('fk_auditorias_proprietario_id_contatos'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_auditorias')),
    sa.UniqueConstraint('numero', name=op.f('uq_auditorias_numero'))
    )
    _indices('auditorias', ['contrato_id', 'corretor_id', 'imovel_id', 'proprietario_id', 'status'])
    op.create_table('auditoria_itens',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('auditoria_id', sa.String(length=36), nullable=False),
    sa.Column('ordem', sa.Integer(), nullable=False),
    sa.Column('area', sa.String(length=100), nullable=False),
    sa.Column('item', sa.String(length=200), nullable=False),
    sa.Column('estado', _enum('estadoitem', ['pendente', 'ok', 'atencao', 'problema', 'naoAplica']), nullable=False),
    sa.Column('observacao', sa.Text(), nullable=False),
    sa.Column('manutencao_id', sa.String(length=36), nullable=True),
    sa.ForeignKeyConstraint(['auditoria_id'], ['auditorias.id'], name=op.f('fk_auditoria_itens_auditoria_id_auditorias'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_auditoria_itens'))
    )
    _indices('auditoria_itens', ['auditoria_id'])
    op.create_table('auditoria_midias',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('auditoria_id', sa.String(length=36), nullable=False),
    sa.Column('item_id', sa.String(length=36), nullable=True),
    sa.Column('arquivo_id', sa.String(length=36), nullable=False),
    sa.Column('tipo', _enum('tipomidia', ['foto', 'video']), nullable=False),
    sa.Column('titulo', sa.String(length=200), nullable=False),
    sa.Column('transcricao_status', _enum('statustranscricao', ['naoSolicitada', 'pendente', 'processando', 'concluida', 'erro']), nullable=False),
    sa.Column('transcricao_texto', sa.Text(), nullable=False),
    sa.Column('transcricao_erro', sa.String(length=500), nullable=False),
    sa.Column('transcricao_em', sa.DateTime(), nullable=True),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['auditoria_id'], ['auditorias.id'], name=op.f('fk_auditoria_midias_auditoria_id_auditorias'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_auditoria_midias'))
    )
    _indices('auditoria_midias', ['arquivo_id', 'auditoria_id', 'transcricao_status'])
    op.create_table('auditoria_modelos',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('nome', sa.String(length=150), nullable=False),
    sa.Column('itens', sa.JSON(), nullable=False),
    sa.Column('padrao', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_auditoria_modelos'))
    )
    op.create_table('configuracao_auditoria',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('dados', sa.JSON(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_configuracao_auditoria'))
    )
    op.create_table('acessos_proprietario',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('contato_id', sa.String(length=36), nullable=False),
    sa.Column('login', sa.String(length=14), nullable=False),
    sa.Column('senha_hash', sa.String(length=200), nullable=False),
    sa.Column('ativo', sa.Boolean(), nullable=False),
    sa.Column('trocar_senha', sa.Boolean(), nullable=False),
    sa.Column('versao', sa.Integer(), nullable=False),
    sa.Column('tentativas', sa.Integer(), nullable=False),
    sa.Column('bloqueado_ate', sa.DateTime(), nullable=True),
    sa.Column('ultimo_acesso', sa.DateTime(), nullable=True),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['contato_id'], ['contatos.id'], name=op.f('fk_acessos_proprietario_contato_id_contatos'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_acessos_proprietario')),
    sa.UniqueConstraint('contato_id', name=op.f('uq_acessos_proprietario_contato_id')),
    sa.UniqueConstraint('login', name=op.f('uq_acessos_proprietario_login'))
    )

    conexao = op.get_bind()
    for uid, perfil, permissoes in conexao.execute(
        sa.text('SELECT id, perfil, permissoes FROM usuarios')
    ).all():
        p = json.loads(permissoes) if isinstance(permissoes, str) else (permissoes or {})
        modulos = p.setdefault('modulos', {})
        if 'auditorias' not in modulos and perfil in _AUDITORIAS:
            modulos['auditorias'] = _AUDITORIAS[perfil]
            conexao.execute(
                sa.text('UPDATE usuarios SET permissoes = :p WHERE id = :id'),
                {'p': json.dumps(p), 'id': uid},
            )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('acessos_proprietario')
    op.drop_table('configuracao_auditoria')
    op.drop_table('auditoria_modelos')
    op.drop_table('auditoria_midias')
    op.drop_table('auditoria_itens')
    op.drop_table('auditorias')

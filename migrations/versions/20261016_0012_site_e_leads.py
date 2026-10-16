"""site público e leads

Revision ID: 0012
Revises: 0011
Create Date: 2026-10-16 20:00:00.000000

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0012'
down_revision: Union[str, Sequence[str], None] = '0011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Permissão do novo módulo para quem já existe, conforme o perfil.
_SITE = {
    'administrador': ['visualizar', 'criar', 'editar', 'excluir'],
    'gerente': ['visualizar', 'criar', 'editar', 'excluir'],
    'atendente': ['visualizar', 'criar', 'editar'],
    'corretor': ['visualizar'],
}


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('imoveis') as t:
        t.add_column(sa.Column('publicar_site', sa.Boolean(), nullable=False, server_default=sa.false()))
        t.add_column(sa.Column('destaque_site', sa.Boolean(), nullable=False, server_default=sa.false()))

    op.create_table('configuracao_site',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('dados', sa.JSON(), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_configuracao_site'))
    )
    op.create_table('leads_site',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('tipo', sa.Enum('interesse', 'visita', 'contato', 'anunciar', name='tipolead', native_enum=False, length=19), nullable=False),
    sa.Column('status', sa.Enum('novo', 'emAtendimento', 'convertido', 'descartado', name='statuslead', native_enum=False, length=23), nullable=False),
    sa.Column('nome', sa.String(length=200), nullable=False),
    sa.Column('email', sa.String(length=200), nullable=False),
    sa.Column('telefone', sa.String(length=30), nullable=False),
    sa.Column('mensagem', sa.Text(), nullable=False),
    sa.Column('data_visita', sa.DateTime(), nullable=True),
    sa.Column('imovel_id', sa.String(length=36), nullable=True),
    sa.Column('contato_id', sa.String(length=36), nullable=True),
    sa.Column('corretor_id', sa.String(length=36), nullable=True),
    sa.Column('atendimento_id', sa.String(length=36), nullable=True),
    sa.Column('evento_id', sa.String(length=36), nullable=True),
    sa.Column('pagina', sa.String(length=300), nullable=False),
    sa.Column('observacao', sa.Text(), nullable=False),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['contato_id'], ['contatos.id'], name=op.f('fk_leads_site_contato_id_contatos'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['corretor_id'], ['usuarios.id'], name=op.f('fk_leads_site_corretor_id_usuarios'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['imovel_id'], ['imoveis.id'], name=op.f('fk_leads_site_imovel_id_imoveis'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_leads_site'))
    )
    for coluna in ('contato_id', 'corretor_id', 'criado_em', 'imovel_id', 'status'):
        op.create_index(op.f(f'ix_leads_site_{coluna}'), 'leads_site', [coluna], unique=False)

    conexao = op.get_bind()
    for uid, perfil, permissoes in conexao.execute(
        sa.text('SELECT id, perfil, permissoes FROM usuarios')
    ).all():
        p = json.loads(permissoes) if isinstance(permissoes, str) else (permissoes or {})
        modulos = p.setdefault('modulos', {})
        if 'site' not in modulos and perfil in _SITE:
            modulos['site'] = _SITE[perfil]
            conexao.execute(
                sa.text('UPDATE usuarios SET permissoes = :p WHERE id = :id'),
                {'p': json.dumps(p), 'id': uid},
            )


def downgrade() -> None:
    """Downgrade schema."""
    for coluna in ('status', 'imovel_id', 'criado_em', 'corretor_id', 'contato_id'):
        op.drop_index(op.f(f'ix_leads_site_{coluna}'), table_name='leads_site')
    op.drop_table('leads_site')
    op.drop_table('configuracao_site')
    with op.batch_alter_table('imoveis') as t:
        t.drop_column('destaque_site')
        t.drop_column('publicar_site')

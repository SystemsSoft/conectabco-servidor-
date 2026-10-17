"""área do inquilino (portal)

Revision ID: 0013
Revises: 0012
Create Date: 2026-10-17 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0013'
down_revision: Union[str, Sequence[str], None] = '0012'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _enum(nome: str, valores: list[str]) -> sa.Enum:
    return sa.Enum(*valores, name=nome, native_enum=False, length=max(map(len, valores)) + 10)


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('manutencoes') as t:
        t.add_column(sa.Column('contrato_id', sa.String(length=36), nullable=True))
        t.add_column(sa.Column('origem', _enum('origemmanutencao', ['equipe', 'inquilino']),
                               nullable=False, server_default='equipe'))
        t.create_foreign_key(op.f('fk_manutencoes_contrato_id_contratos_locacao'),
                             'contratos_locacao', ['contrato_id'], ['id'], ondelete='SET NULL')
        t.create_index(op.f('ix_manutencoes_contrato_id'), ['contrato_id'], unique=False)

    op.create_table('acessos_inquilino',
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
    sa.ForeignKeyConstraint(['contato_id'], ['contatos.id'], name=op.f('fk_acessos_inquilino_contato_id_contatos'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_acessos_inquilino')),
    sa.UniqueConstraint('contato_id', name=op.f('uq_acessos_inquilino_contato_id')),
    sa.UniqueConstraint('login', name=op.f('uq_acessos_inquilino_login'))
    )
    op.create_table('arquivos_contrato',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('contrato_id', sa.String(length=36), nullable=False),
    sa.Column('manutencao_id', sa.String(length=36), nullable=True),
    sa.Column('tipo', _enum('tipoarquivocontrato', ['contrato', 'vistoria', 'documento', 'estadoImovel', 'chamado']), nullable=False),
    sa.Column('origem', _enum('origemarquivo', ['imobiliaria', 'inquilino']), nullable=False),
    sa.Column('titulo', sa.String(length=200), nullable=False),
    sa.Column('observacao', sa.Text(), nullable=False),
    sa.Column('arquivo_id', sa.String(length=36), nullable=False),
    sa.Column('visivel_inquilino', sa.Boolean(), nullable=False),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['contrato_id'], ['contratos_locacao.id'], name=op.f('fk_arquivos_contrato_contrato_id_contratos_locacao'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['manutencao_id'], ['manutencoes.id'], name=op.f('fk_arquivos_contrato_manutencao_id_manutencoes'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_arquivos_contrato'))
    )
    for coluna in ('arquivo_id', 'contrato_id', 'criado_em', 'manutencao_id'):
        op.create_index(op.f(f'ix_arquivos_contrato_{coluna}'), 'arquivos_contrato', [coluna], unique=False)
    op.create_table('comunicados_inquilino',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('contrato_id', sa.String(length=36), nullable=True),
    sa.Column('titulo', sa.String(length=200), nullable=False),
    sa.Column('mensagem', sa.Text(), nullable=False),
    sa.Column('automatico', sa.Boolean(), nullable=False),
    sa.Column('enviado_por_id', sa.String(length=36), nullable=True),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['contrato_id'], ['contratos_locacao.id'], name=op.f('fk_comunicados_inquilino_contrato_id_contratos_locacao'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_comunicados_inquilino'))
    )
    for coluna in ('contrato_id', 'criado_em'):
        op.create_index(op.f(f'ix_comunicados_inquilino_{coluna}'), 'comunicados_inquilino', [coluna], unique=False)
    op.create_table('leituras_comunicado',
    sa.Column('comunicado_id', sa.String(length=36), nullable=False),
    sa.Column('acesso_id', sa.String(length=36), nullable=False),
    sa.Column('lido_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['acesso_id'], ['acessos_inquilino.id'], name=op.f('fk_leituras_comunicado_acesso_id_acessos_inquilino'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['comunicado_id'], ['comunicados_inquilino.id'], name=op.f('fk_leituras_comunicado_comunicado_id_comunicados_inquilino'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('comunicado_id', 'acesso_id', name=op.f('pk_leituras_comunicado'))
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('leituras_comunicado')
    op.drop_table('comunicados_inquilino')
    op.drop_table('arquivos_contrato')
    op.drop_table('acessos_inquilino')
    with op.batch_alter_table('manutencoes') as t:
        t.drop_index(op.f('ix_manutencoes_contrato_id'))
        t.drop_constraint(op.f('fk_manutencoes_contrato_id_contratos_locacao'), type_='foreignkey')
        t.drop_column('origem')
        t.drop_column('contrato_id')

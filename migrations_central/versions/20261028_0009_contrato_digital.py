"""contratação pelo site: contrato digital e assinatura

Revision ID: c0009
Revises: c0008
Create Date: 2026-10-28 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c0009'
down_revision: Union[str, Sequence[str], None] = 'c0008'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('contratos_digitais',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('token', sa.String(length=64), nullable=False),
    sa.Column('dados', sa.JSON(), nullable=False),
    sa.Column('email', sa.String(length=200), nullable=False),
    sa.Column('situacao', sa.String(length=20), nullable=False),
    sa.Column('metodo', sa.String(length=20), nullable=False),
    sa.Column('assinado_em', sa.DateTime(), nullable=True),
    sa.Column('assinatura_nome', sa.String(length=150), nullable=False),
    sa.Column('ip', sa.String(length=64), nullable=False),
    sa.Column('navegador', sa.String(length=300), nullable=False),
    sa.Column('hash_contrato', sa.String(length=64), nullable=False),
    sa.Column('chave_assinado', sa.String(length=160), nullable=False),
    sa.Column('solicitacao_id', sa.String(length=36), nullable=True),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['solicitacao_id'], ['solicitacoes_implantacao.id'], name=op.f('fk_contratos_digitais_solicitacao_id_solicitacoes_implantacao'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_contratos_digitais')),
    sa.UniqueConstraint('token', name=op.f('uq_contratos_digitais_token'))
    )
    op.create_index(op.f('ix_contratos_digitais_situacao'), 'contratos_digitais', ['situacao'], unique=False)
    op.create_index(op.f('ix_contratos_digitais_solicitacao_id'), 'contratos_digitais', ['solicitacao_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_contratos_digitais_solicitacao_id'), table_name='contratos_digitais')
    op.drop_index(op.f('ix_contratos_digitais_situacao'), table_name='contratos_digitais')
    op.drop_table('contratos_digitais')

"""pastas e documentos do financeiro

Revision ID: 0018
Revises: 0017
Create Date: 2026-10-20 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0018'
down_revision: Union[str, Sequence[str], None] = '0017'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('pastas_documentos',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('nome', sa.String(length=100), nullable=False),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_pastas_documentos'))
    )
    op.create_table('documentos_financeiro',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('pasta_id', sa.String(length=36), nullable=False),
    sa.Column('nome', sa.String(length=255), nullable=False),
    sa.Column('arquivo_id', sa.String(length=36), nullable=False),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['pasta_id'], ['pastas_documentos.id'], name=op.f('fk_documentos_financeiro_pasta_id_pastas_documentos'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_documentos_financeiro'))
    )
    op.create_index(op.f('ix_documentos_financeiro_pasta_id'), 'documentos_financeiro', ['pasta_id'], unique=False)
    op.create_index(op.f('ix_documentos_financeiro_arquivo_id'), 'documentos_financeiro', ['arquivo_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_documentos_financeiro_arquivo_id'), table_name='documentos_financeiro')
    op.drop_index(op.f('ix_documentos_financeiro_pasta_id'), table_name='documentos_financeiro')
    op.drop_table('documentos_financeiro')
    op.drop_table('pastas_documentos')

"""compartilhamento de pastas do financeiro com inquilinos e proprietários

Revision ID: 0019
Revises: 0018
Create Date: 2026-10-20 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0019'
down_revision: Union[str, Sequence[str], None] = '0018'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('compartilhamentos_pasta',
    sa.Column('pasta_id', sa.String(length=36), nullable=False),
    sa.Column('contato_id', sa.String(length=36), nullable=False),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['contato_id'], ['contatos.id'], name=op.f('fk_compartilhamentos_pasta_contato_id_contatos'), ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['pasta_id'], ['pastas_documentos.id'], name=op.f('fk_compartilhamentos_pasta_pasta_id_pastas_documentos'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('pasta_id', 'contato_id', name=op.f('pk_compartilhamentos_pasta'))
    )
    op.create_index(op.f('ix_compartilhamentos_pasta_contato_id'), 'compartilhamentos_pasta', ['contato_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_compartilhamentos_pasta_contato_id'), table_name='compartilhamentos_pasta')
    op.drop_table('compartilhamentos_pasta')

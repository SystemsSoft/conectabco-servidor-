"""imobiliarias

Revision ID: c0001
Revises:
Create Date: 2026-10-23 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c0001'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('imobiliarias',
    sa.Column('slug', sa.String(length=40), nullable=False),
    sa.Column('nome', sa.String(length=200), nullable=False),
    sa.Column('banco', sa.String(length=64), nullable=False),
    sa.Column('site_url', sa.String(length=200), nullable=False),
    sa.Column('ativa', sa.Boolean(), nullable=False),
    sa.Column('criada_em', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('slug', name=op.f('pk_imobiliarias')),
    sa.UniqueConstraint('banco', name=op.f('uq_imobiliarias_banco'))
    )
    op.create_table('dominios',
    sa.Column('dominio', sa.String(length=253), nullable=False),
    sa.Column('imobiliaria_slug', sa.String(length=40), nullable=False),
    sa.ForeignKeyConstraint(['imobiliaria_slug'], ['imobiliarias.slug'], name=op.f('fk_dominios_imobiliaria_slug_imobiliarias'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('dominio', name=op.f('pk_dominios'))
    )
    op.create_index(op.f('ix_dominios_imobiliaria_slug'), 'dominios', ['imobiliaria_slug'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_dominios_imobiliaria_slug'), table_name='dominios')
    op.drop_table('dominios')
    op.drop_table('imobiliarias')

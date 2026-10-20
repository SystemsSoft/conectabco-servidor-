"""link do internet banking nas contas bancárias

Revision ID: 0016
Revises: 0015
Create Date: 2026-10-20 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0016'
down_revision: Union[str, Sequence[str], None] = '0015'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('contas_bancarias') as t:
        t.add_column(sa.Column('link_internet_banking', sa.String(length=300), nullable=False, server_default=''))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('contas_bancarias') as t:
        t.drop_column('link_internet_banking')

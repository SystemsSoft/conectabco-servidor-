"""link do banco na configuração do financeiro (em vez de por conta)

Revision ID: 0017
Revises: 0016
Create Date: 2026-10-20 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0017'
down_revision: Union[str, Sequence[str], None] = '0016'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('contas_bancarias') as t:
        t.drop_column('link_internet_banking')
    with op.batch_alter_table('configuracao_financeira') as t:
        t.add_column(sa.Column('link_banco', sa.String(length=300), nullable=False, server_default=''))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('configuracao_financeira') as t:
        t.drop_column('link_banco')
    with op.batch_alter_table('contas_bancarias') as t:
        t.add_column(sa.Column('link_internet_banking', sa.String(length=300), nullable=False, server_default=''))

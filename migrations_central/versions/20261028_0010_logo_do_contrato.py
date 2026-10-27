"""logotipo enviado na contratação pelo site

Revision ID: c0010
Revises: c0009
Create Date: 2026-10-28 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c0010'
down_revision: Union[str, Sequence[str], None] = 'c0009'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('contratos_digitais') as tabela:
        tabela.add_column(sa.Column('logo_chave', sa.String(length=160), nullable=False, server_default=''))
        tabela.add_column(sa.Column('logo_tipo', sa.String(length=20), nullable=False, server_default=''))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('contratos_digitais') as tabela:
        tabela.drop_column('logo_tipo')
        tabela.drop_column('logo_chave')

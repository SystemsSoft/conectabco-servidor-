"""conta Google conectada pelo representante

Revision ID: c0012
Revises: c0011
Create Date: 2026-11-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c0012'
down_revision: Union[str, Sequence[str], None] = 'c0011'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('representantes', sa.Column('google_uid', sa.String(length=128), nullable=True))
    op.add_column('representantes', sa.Column('google_email', sa.String(length=200), nullable=False, server_default=''))
    op.create_unique_constraint(op.f('uq_representantes_google_uid'), 'representantes', ['google_uid'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f('uq_representantes_google_uid'), 'representantes', type_='unique')
    op.drop_column('representantes', 'google_email')
    op.drop_column('representantes', 'google_uid')

"""chave (ULID) de cada arquivo no armazenamento (S3)

Revision ID: 0020
Revises: 0019
Create Date: 2026-10-24 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0020'
down_revision: Union[str, Sequence[str], None] = '0019'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Vazia nos arquivos de antes do S3, até o gerenciar.py migrar-arquivos.
    op.add_column('arquivos', sa.Column('chave', sa.String(length=120), nullable=True))
    op.create_unique_constraint(op.f('uq_arquivos_chave'), 'arquivos', ['chave'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(op.f('uq_arquivos_chave'), 'arquivos', type_='unique')
    op.drop_column('arquivos', 'chave')

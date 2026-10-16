"""arquivos enviados (fotos, vídeos e documentos)

Revision ID: 0011
Revises: 0010
Create Date: 2026-10-16 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0011'
down_revision: Union[str, Sequence[str], None] = '0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('arquivos',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('nome', sa.String(length=255), nullable=False),
    sa.Column('categoria', sa.String(length=20), nullable=False),
    sa.Column('tipo_mime', sa.String(length=120), nullable=False),
    sa.Column('tamanho', sa.BigInteger(), nullable=False),
    sa.Column('enviado_por_id', sa.String(length=36), nullable=True),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_arquivos'))
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('arquivos')

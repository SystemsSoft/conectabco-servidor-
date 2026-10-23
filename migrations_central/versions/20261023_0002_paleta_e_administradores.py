"""paleta e administradores

Revision ID: c0002
Revises: c0001
Create Date: 2026-10-23 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c0002'
down_revision: Union[str, Sequence[str], None] = 'c0001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('imobiliarias', sa.Column('cor_primaria', sa.String(length=7), nullable=False, server_default=''))
    op.add_column('imobiliarias', sa.Column('cor_destaque', sa.String(length=7), nullable=False, server_default=''))
    op.create_table('administradores',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('nome', sa.String(length=150), nullable=False),
    sa.Column('login', sa.String(length=60), nullable=False),
    sa.Column('senha_hash', sa.String(length=200), nullable=False),
    sa.Column('ativo', sa.Boolean(), nullable=False),
    sa.Column('versao', sa.Integer(), nullable=False),
    sa.Column('tentativas', sa.Integer(), nullable=False),
    sa.Column('bloqueado_ate', sa.DateTime(), nullable=True),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.Column('ultimo_acesso', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_administradores')),
    sa.UniqueConstraint('login', name=op.f('uq_administradores_login'))
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('administradores')
    op.drop_column('imobiliarias', 'cor_destaque')
    op.drop_column('imobiliarias', 'cor_primaria')

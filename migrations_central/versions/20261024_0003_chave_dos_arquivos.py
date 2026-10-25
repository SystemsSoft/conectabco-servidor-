"""chave (ULID) de cada imobiliária: prefixo dos arquivos no S3

Revision ID: c0003
Revises: c0002
Create Date: 2026-10-24 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.core.ulid import novo_ulid


# revision identifiers, used by Alembic.
revision: str = 'c0003'
down_revision: Union[str, Sequence[str], None] = 'c0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('imobiliarias', sa.Column('chave', sa.String(length=26), nullable=True))
    conexao = op.get_bind()
    imobiliarias = sa.table('imobiliarias', sa.column('slug', sa.String), sa.column('chave', sa.String))
    for (slug,) in conexao.execute(sa.select(imobiliarias.c.slug)).all():
        conexao.execute(imobiliarias.update().where(imobiliarias.c.slug == slug).values(chave=novo_ulid()))
    with op.batch_alter_table('imobiliarias') as tabela:
        tabela.alter_column('chave', existing_type=sa.String(length=26), nullable=False)
        tabela.create_unique_constraint(op.f('uq_imobiliarias_chave'), ['chave'])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('imobiliarias') as tabela:
        tabela.drop_constraint(op.f('uq_imobiliarias_chave'), type_='unique')
        tabela.drop_column('chave')

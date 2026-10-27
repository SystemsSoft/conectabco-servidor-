"""solicitação de implantação cadastrada direto no painel (sem representante)

Revision ID: c0006
Revises: c0005
Create Date: 2026-10-27 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c0006'
down_revision: Union[str, Sequence[str], None] = 'c0005'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('solicitacoes_implantacao') as tabela:
        tabela.alter_column('representante_id', existing_type=sa.String(length=36), nullable=True)
        tabela.add_column(sa.Column('administrador_id', sa.String(length=36), nullable=True))
        tabela.create_foreign_key(op.f('fk_solicitacoes_implantacao_administrador_id_administradores'),
                                  'administradores', ['administrador_id'], ['id'])


def downgrade() -> None:
    """Downgrade schema (apaga as solicitações cadastradas no painel)."""
    op.execute("DELETE FROM solicitacoes_implantacao WHERE representante_id IS NULL")
    with op.batch_alter_table('solicitacoes_implantacao') as tabela:
        tabela.drop_constraint(op.f('fk_solicitacoes_implantacao_administrador_id_administradores'), type_='foreignkey')
        tabela.drop_column('administrador_id')
        tabela.alter_column('representante_id', existing_type=sa.String(length=36), nullable=False)

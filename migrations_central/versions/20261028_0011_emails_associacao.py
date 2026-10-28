"""caixa de e-mail da associação no painel

Revision ID: c0011
Revises: c0010
Create Date: 2026-10-28 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


# revision identifiers, used by Alembic.
revision: str = 'c0011'
down_revision: Union[str, Sequence[str], None] = 'c0010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TextoLongo = sa.Text().with_variant(mysql.MEDIUMTEXT(), "mysql")


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('emails_associacao',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('pasta', sa.String(length=10), nullable=False),
    sa.Column('uid', sa.BigInteger(), nullable=True),
    sa.Column('uidvalidity', sa.BigInteger(), nullable=True),
    sa.Column('message_id', sa.String(length=300), nullable=False),
    sa.Column('em_resposta_a', sa.String(length=300), nullable=False),
    sa.Column('de_nome', sa.String(length=200), nullable=False),
    sa.Column('de_email', sa.String(length=200), nullable=False),
    sa.Column('para', sa.Text(), nullable=False),
    sa.Column('cc', sa.Text(), nullable=False),
    sa.Column('assunto', sa.String(length=500), nullable=False),
    sa.Column('data', sa.DateTime(), nullable=False),
    sa.Column('texto', TextoLongo, nullable=False),
    sa.Column('html', TextoLongo, nullable=False),
    sa.Column('anexos', sa.JSON(), nullable=False),
    sa.Column('lido', sa.Boolean(), nullable=False),
    sa.Column('respondido_em', sa.DateTime(), nullable=True),
    sa.Column('enviado_por_id', sa.String(length=36), nullable=True),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['enviado_por_id'], ['administradores.id'], name=op.f('fk_emails_associacao_enviado_por_id_administradores'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_emails_associacao')),
    sa.UniqueConstraint('pasta', 'uidvalidity', 'uid', name=op.f('uq_emails_associacao_pasta'))
    )
    op.create_index(op.f('ix_emails_associacao_pasta'), 'emails_associacao', ['pasta'], unique=False)
    op.create_index(op.f('ix_emails_associacao_de_email'), 'emails_associacao', ['de_email'], unique=False)
    op.create_index(op.f('ix_emails_associacao_data'), 'emails_associacao', ['data'], unique=False)
    op.create_index(op.f('ix_emails_associacao_lido'), 'emails_associacao', ['lido'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_emails_associacao_lido'), table_name='emails_associacao')
    op.drop_index(op.f('ix_emails_associacao_data'), table_name='emails_associacao')
    op.drop_index(op.f('ix_emails_associacao_de_email'), table_name='emails_associacao')
    op.drop_index(op.f('ix_emails_associacao_pasta'), table_name='emails_associacao')
    op.drop_table('emails_associacao')

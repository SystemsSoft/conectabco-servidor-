"""comercial: plano das imobiliárias, cancelamento, implantação e leads do site

Revision ID: c0008
Revises: c0007
Create Date: 2026-10-28 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c0008'
down_revision: Union[str, Sequence[str], None] = 'c0007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('imobiliarias') as tabela:
        tabela.add_column(sa.Column('desativada_em', sa.DateTime(), nullable=True))
        tabela.add_column(sa.Column('mensalidade', sa.Numeric(precision=10, scale=2), nullable=False, server_default='150.00'))
        tabela.add_column(sa.Column('dia_vencimento', sa.Integer(), nullable=False, server_default='5'))
    # As já desativadas contam como canceladas a partir de agora.
    op.execute("UPDATE imobiliarias SET desativada_em = CURRENT_TIMESTAMP WHERE ativa = 0 OR ativa IS FALSE")
    with op.batch_alter_table('solicitacoes_implantacao') as tabela:
        tabela.add_column(sa.Column('implantada_em', sa.DateTime(), nullable=True))
    op.execute("UPDATE solicitacoes_implantacao SET implantada_em = atualizada_em WHERE situacao = 'implantada'")
    op.create_table('leads_associacao',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('nome', sa.String(length=150), nullable=False),
    sa.Column('email', sa.String(length=200), nullable=False),
    sa.Column('whatsapp', sa.String(length=30), nullable=False),
    sa.Column('creci', sa.String(length=30), nullable=False),
    sa.Column('cidade', sa.String(length=150), nullable=False),
    sa.Column('perfil', sa.String(length=40), nullable=False),
    sa.Column('quer_sistema', sa.Boolean(), nullable=False),
    sa.Column('situacao', sa.String(length=20), nullable=False),
    sa.Column('anotacao', sa.Text(), nullable=False),
    sa.Column('solicitacao_id', sa.String(length=36), nullable=True),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['solicitacao_id'], ['solicitacoes_implantacao.id'], name=op.f('fk_leads_associacao_solicitacao_id_solicitacoes_implantacao'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_leads_associacao'))
    )
    op.create_index(op.f('ix_leads_associacao_situacao'), 'leads_associacao', ['situacao'], unique=False)
    op.create_index(op.f('ix_leads_associacao_criado_em'), 'leads_associacao', ['criado_em'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_leads_associacao_criado_em'), table_name='leads_associacao')
    op.drop_index(op.f('ix_leads_associacao_situacao'), table_name='leads_associacao')
    op.drop_table('leads_associacao')
    with op.batch_alter_table('solicitacoes_implantacao') as tabela:
        tabela.drop_column('implantada_em')
    with op.batch_alter_table('imobiliarias') as tabela:
        tabela.drop_column('dia_vencimento')
        tabela.drop_column('mensalidade')
        tabela.drop_column('desativada_em')

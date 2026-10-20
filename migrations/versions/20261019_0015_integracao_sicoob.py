"""integração Sicoob (sandbox)

Revision ID: 0015
Revises: 0014
Create Date: 2026-10-19 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0015'
down_revision: Union[str, Sequence[str], None] = '0014'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DINHEIRO = sa.Numeric(precision=14, scale=2, asdecimal=False)


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('configuracao_sicoob',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('dados', sa.JSON(), nullable=False),
    sa.Column('token_sandbox', sa.Text(), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_configuracao_sicoob'))
    )
    op.create_table('sicoob_chamadas',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.Column('usuario_id', sa.String(length=36), nullable=True),
    sa.Column('ambiente', sa.String(length=20), nullable=False),
    sa.Column('api', sa.String(length=20), nullable=False),
    sa.Column('operacao', sa.String(length=100), nullable=False),
    sa.Column('metodo', sa.String(length=10), nullable=False),
    sa.Column('caminho', sa.String(length=500), nullable=False),
    sa.Column('status_http', sa.Integer(), nullable=True),
    sa.Column('duracao_ms', sa.Integer(), nullable=False),
    sa.Column('sucesso', sa.Boolean(), nullable=False),
    sa.Column('requisicao', sa.Text(), nullable=False),
    sa.Column('resposta', sa.Text(), nullable=False),
    sa.Column('erro', sa.String(length=500), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sicoob_chamadas'))
    )
    op.create_index(op.f('ix_sicoob_chamadas_criado_em'), 'sicoob_chamadas', ['criado_em'], unique=False)
    op.create_table('sicoob_boletos',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('ambiente', sa.String(length=20), nullable=False),
    sa.Column('nosso_numero', sa.String(length=30), nullable=False),
    sa.Column('seu_numero', sa.String(length=30), nullable=False),
    sa.Column('valor', _DINHEIRO, nullable=False),
    sa.Column('vencimento', sa.Date(), nullable=False),
    sa.Column('pagador_nome', sa.String(length=200), nullable=False),
    sa.Column('pagador_documento', sa.String(length=20), nullable=False),
    sa.Column('linha_digitavel', sa.String(length=80), nullable=False),
    sa.Column('codigo_barras', sa.String(length=60), nullable=False),
    sa.Column('situacao', sa.String(length=60), nullable=False),
    sa.Column('cobranca_id', sa.String(length=36), nullable=True),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['cobranca_id'], ['cobrancas_locacao.id'], name=op.f('fk_sicoob_boletos_cobranca_id_cobrancas_locacao'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sicoob_boletos'))
    )
    op.create_index(op.f('ix_sicoob_boletos_cobranca_id'), 'sicoob_boletos', ['cobranca_id'], unique=False)
    op.create_index(op.f('ix_sicoob_boletos_nosso_numero'), 'sicoob_boletos', ['nosso_numero'], unique=False)
    op.create_table('sicoob_pix',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('ambiente', sa.String(length=20), nullable=False),
    sa.Column('txid', sa.String(length=40), nullable=False),
    sa.Column('valor', _DINHEIRO, nullable=False),
    sa.Column('devedor_nome', sa.String(length=200), nullable=False),
    sa.Column('devedor_documento', sa.String(length=20), nullable=False),
    sa.Column('descricao', sa.String(length=140), nullable=False),
    sa.Column('status', sa.String(length=40), nullable=False),
    sa.Column('copia_e_cola', sa.Text(), nullable=False),
    sa.Column('location', sa.String(length=300), nullable=False),
    sa.Column('cobranca_id', sa.String(length=36), nullable=True),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.Column('atualizado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['cobranca_id'], ['cobrancas_locacao.id'], name=op.f('fk_sicoob_pix_cobranca_id_cobrancas_locacao'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_sicoob_pix'))
    )
    op.create_index(op.f('ix_sicoob_pix_cobranca_id'), 'sicoob_pix', ['cobranca_id'], unique=False)
    op.create_index(op.f('ix_sicoob_pix_txid'), 'sicoob_pix', ['txid'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('sicoob_pix')
    op.drop_table('sicoob_boletos')
    op.drop_table('sicoob_chamadas')
    op.drop_table('configuracao_sicoob')

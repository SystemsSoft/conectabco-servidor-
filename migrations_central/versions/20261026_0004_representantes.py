"""representantes e solicitações de implantação

Revision ID: c0004
Revises: c0003
Create Date: 2026-10-26 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c0004'
down_revision: Union[str, Sequence[str], None] = 'c0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('representantes',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('nome', sa.String(length=150), nullable=False),
    sa.Column('login', sa.String(length=60), nullable=False),
    sa.Column('email', sa.String(length=200), nullable=False),
    sa.Column('telefone', sa.String(length=30), nullable=False),
    sa.Column('regiao', sa.String(length=150), nullable=False),
    sa.Column('senha_hash', sa.String(length=200), nullable=False),
    sa.Column('ativo', sa.Boolean(), nullable=False),
    sa.Column('versao', sa.Integer(), nullable=False),
    sa.Column('tentativas', sa.Integer(), nullable=False),
    sa.Column('bloqueado_ate', sa.DateTime(), nullable=True),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.Column('ultimo_acesso', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_representantes')),
    sa.UniqueConstraint('login', name=op.f('uq_representantes_login'))
    )
    op.create_table('solicitacoes_implantacao',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('representante_id', sa.String(length=36), nullable=False),
    sa.Column('situacao', sa.String(length=20), nullable=False),
    sa.Column('nome', sa.String(length=150), nullable=False),
    sa.Column('cpf_cnpj', sa.String(length=18), nullable=False),
    sa.Column('creci', sa.String(length=30), nullable=False),
    sa.Column('email', sa.String(length=200), nullable=False),
    sa.Column('telefone', sa.String(length=30), nullable=False),
    sa.Column('nome_imobiliaria', sa.String(length=200), nullable=False),
    sa.Column('cidade', sa.String(length=120), nullable=False),
    sa.Column('uf', sa.String(length=2), nullable=False),
    sa.Column('dominio', sa.String(length=253), nullable=False),
    sa.Column('imoveis', sa.Integer(), nullable=True),
    sa.Column('contratos', sa.Integer(), nullable=True),
    sa.Column('usuarios', sa.Integer(), nullable=True),
    sa.Column('observacoes', sa.Text(), nullable=False),
    sa.Column('resposta', sa.Text(), nullable=False),
    sa.Column('imobiliaria_slug', sa.String(length=40), nullable=True),
    sa.Column('criada_em', sa.DateTime(), nullable=False),
    sa.Column('atualizada_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['imobiliaria_slug'], ['imobiliarias.slug'], name=op.f('fk_solicitacoes_implantacao_imobiliaria_slug_imobiliarias'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['representante_id'], ['representantes.id'], name=op.f('fk_solicitacoes_implantacao_representante_id_representantes')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_solicitacoes_implantacao'))
    )
    op.create_index(op.f('ix_solicitacoes_implantacao_representante_id'), 'solicitacoes_implantacao', ['representante_id'], unique=False)
    op.create_index(op.f('ix_solicitacoes_implantacao_situacao'), 'solicitacoes_implantacao', ['situacao'], unique=False)
    op.create_index(op.f('ix_solicitacoes_implantacao_criada_em'), 'solicitacoes_implantacao', ['criada_em'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_solicitacoes_implantacao_criada_em'), table_name='solicitacoes_implantacao')
    op.drop_index(op.f('ix_solicitacoes_implantacao_situacao'), table_name='solicitacoes_implantacao')
    op.drop_index(op.f('ix_solicitacoes_implantacao_representante_id'), table_name='solicitacoes_implantacao')
    op.drop_table('solicitacoes_implantacao')
    op.drop_table('representantes')

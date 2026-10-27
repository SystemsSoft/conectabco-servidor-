"""dados do contratante (contrato de prestação de serviços)

Revision ID: c0005
Revises: c0004
Create Date: 2026-10-27 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c0005'
down_revision: Union[str, Sequence[str], None] = 'c0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('dados_contratante',
    sa.Column('imobiliaria_slug', sa.String(length=40), nullable=False),
    sa.Column('nome', sa.String(length=150), nullable=False),
    sa.Column('endereco', sa.String(length=200), nullable=False),
    sa.Column('numero', sa.String(length=20), nullable=False),
    sa.Column('bairro', sa.String(length=100), nullable=False),
    sa.Column('cidade', sa.String(length=120), nullable=False),
    sa.Column('uf', sa.String(length=2), nullable=False),
    sa.Column('cpf', sa.String(length=11), nullable=False),
    sa.Column('identidade', sa.String(length=30), nullable=False),
    sa.Column('cnpj', sa.String(length=14), nullable=False),
    sa.Column('creci_pj', sa.String(length=30), nullable=False),
    sa.Column('creci', sa.String(length=30), nullable=False),
    sa.Column('nome_comercial', sa.String(length=200), nullable=False),
    sa.Column('endereco_comercial', sa.String(length=300), nullable=False),
    sa.Column('telefone_1', sa.String(length=30), nullable=False),
    sa.Column('telefone_2', sa.String(length=30), nullable=False),
    sa.Column('servidor', sa.String(length=150), nullable=False),
    sa.Column('dns', sa.String(length=150), nullable=False),
    sa.Column('instagram', sa.String(length=200), nullable=False),
    sa.Column('facebook', sa.String(length=200), nullable=False),
    sa.Column('tiktok', sa.String(length=200), nullable=False),
    sa.Column('youtube', sa.String(length=200), nullable=False),
    sa.Column('data_implantacao', sa.Date(), nullable=True),
    sa.Column('horario_implantacao', sa.String(length=5), nullable=False),
    sa.Column('data_assinatura', sa.Date(), nullable=True),
    sa.Column('atualizado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['imobiliaria_slug'], ['imobiliarias.slug'], name=op.f('fk_dados_contratante_imobiliaria_slug_imobiliarias'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('imobiliaria_slug', name=op.f('pk_dados_contratante'))
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('dados_contratante')

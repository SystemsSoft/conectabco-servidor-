"""financeiro da solicitação: 1º pagamento e documentos

Revision ID: c0007
Revises: c0006
Create Date: 2026-10-27 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c0007'
down_revision: Union[str, Sequence[str], None] = 'c0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('solicitacoes_implantacao') as tabela:
        tabela.add_column(sa.Column('primeiro_pagamento_em', sa.Date(), nullable=True))
        tabela.add_column(sa.Column('primeiro_pagamento_confirmado_em', sa.DateTime(), nullable=True))
        tabela.add_column(sa.Column('primeiro_pagamento_por_id', sa.String(length=36), nullable=True))
        tabela.add_column(sa.Column('observacao_financeira', sa.Text(), nullable=False, server_default=''))
        tabela.create_foreign_key(op.f('fk_solicitacoes_implantacao_primeiro_pagamento_por_id_administradores'),
                                  'administradores', ['primeiro_pagamento_por_id'], ['id'])
    op.create_table('documentos_solicitacao',
    sa.Column('id', sa.String(length=36), nullable=False),
    sa.Column('solicitacao_id', sa.String(length=36), nullable=False),
    sa.Column('tipo', sa.String(length=20), nullable=False),
    sa.Column('nome', sa.String(length=255), nullable=False),
    sa.Column('descricao', sa.String(length=300), nullable=False),
    sa.Column('tipo_mime', sa.String(length=120), nullable=False),
    sa.Column('tamanho', sa.BigInteger(), nullable=False),
    sa.Column('chave', sa.String(length=160), nullable=False),
    sa.Column('enviado_por_id', sa.String(length=36), nullable=True),
    sa.Column('criado_em', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['enviado_por_id'], ['administradores.id'], name=op.f('fk_documentos_solicitacao_enviado_por_id_administradores')),
    sa.ForeignKeyConstraint(['solicitacao_id'], ['solicitacoes_implantacao.id'], name=op.f('fk_documentos_solicitacao_solicitacao_id_solicitacoes_implantacao'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_documentos_solicitacao')),
    sa.UniqueConstraint('chave', name=op.f('uq_documentos_solicitacao_chave'))
    )
    op.create_index(op.f('ix_documentos_solicitacao_solicitacao_id'), 'documentos_solicitacao', ['solicitacao_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_documentos_solicitacao_solicitacao_id'), table_name='documentos_solicitacao')
    op.drop_table('documentos_solicitacao')
    with op.batch_alter_table('solicitacoes_implantacao') as tabela:
        tabela.drop_constraint(op.f('fk_solicitacoes_implantacao_primeiro_pagamento_por_id_administradores'), type_='foreignkey')
        tabela.drop_column('observacao_financeira')
        tabela.drop_column('primeiro_pagamento_por_id')
        tabela.drop_column('primeiro_pagamento_confirmado_em')
        tabela.drop_column('primeiro_pagamento_em')

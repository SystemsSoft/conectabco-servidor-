"""login por nome de usuário (e-mail vira contato opcional)

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-16

"""
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, Sequence[str], None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("usuarios", sa.Column("login", sa.String(length=60), nullable=True))

    # Usuários existentes: login = parte do e-mail antes do "@" (sem repetir).
    conexao = op.get_bind()
    usados: set[str] = set()
    for id_, email in conexao.execute(sa.text("SELECT id, email FROM usuarios")):
        base = re.sub(r"[^A-Za-z0-9._-]", "", (email or "").split("@")[0])[:55]
        if len(base) < 3:
            base = f"usuario{base}"
        login, n = base, 2
        while login.lower() in usados:
            login, n = f"{base}{n}", n + 1
        usados.add(login.lower())
        conexao.execute(
            sa.text("UPDATE usuarios SET login = :login WHERE id = :id"),
            {"login": login, "id": id_},
        )

    op.alter_column(
        "usuarios", "login", existing_type=sa.String(length=60), nullable=False
    )
    op.create_unique_constraint(op.f("uq_usuarios_login"), "usuarios", ["login"])
    op.drop_constraint(op.f("uq_usuarios_email"), "usuarios", type_="unique")


def downgrade() -> None:
    op.create_unique_constraint(op.f("uq_usuarios_email"), "usuarios", ["email"])
    op.drop_constraint(op.f("uq_usuarios_login"), "usuarios", type_="unique")
    op.drop_column("usuarios", "login")

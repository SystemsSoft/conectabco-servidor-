"""Tarefas administrativas do servidor.

  python gerenciar.py criar-admin
      Cria (ou redefine a senha de) um administrador. Use no primeiro acesso
      ou se esquecer a senha do administrador.
"""

import argparse
import getpass
import sys

from sqlalchemy.orm import Session

from app.core.database import get_engine
from app.core.errors import RegraNegocio
from app.modules import carregar_models


def criar_admin(args: argparse.Namespace) -> None:
    from app.modules.equipe.services import criar_administrador

    nome = args.nome or input("Nome: ").strip()
    login = args.login or input("Usuário (login): ").strip()
    email = args.email if args.email is not None else ""
    senha = args.senha
    if not senha:
        senha = getpass.getpass("Senha (mín. 8 caracteres): ")
        if senha != getpass.getpass("Repita a senha: "):
            sys.exit("As senhas não conferem.")
    with Session(get_engine()) as db:
        try:
            u = criar_administrador(db, nome, login, senha, email)
        except RegraNegocio as e:
            sys.exit(e.mensagem)
        print(f"Administrador pronto: {u.nome} (usuário: {u.login})")


def main() -> None:
    carregar_models()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="comando", required=True)
    c = sub.add_parser("criar-admin", help="cria ou redefine um administrador")
    c.add_argument("--nome")
    c.add_argument("--login", help="nome de usuário para entrar")
    c.add_argument("--email", help="opcional, só contato")
    c.add_argument("--senha", help="evite: prefira digitar quando pedido")
    c.set_defaults(func=criar_admin)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

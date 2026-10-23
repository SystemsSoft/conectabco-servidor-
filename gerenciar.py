"""Tarefas administrativas do servidor.

Imobiliárias (mesmas regras de negócio; cada uma com o seu banco de dados):

  python gerenciar.py imobiliaria criar --slug marcelo --nome "Marcelo Bonifácio"
          [--dominio www.exemplo.com.br ...] [--site-url https://...]
          [--banco imob_marcelo] [--existente] [--sem-admin]
      Cadastra a imobiliária, cria o banco dela, aplica as migrações e cria o
      administrador. Com --existente, usa um banco que já tem dados (ex.: o
      da imobiliária de antes do multi-imobiliária).

  python gerenciar.py imobiliaria listar
  python gerenciar.py imobiliaria editar <slug> [--nome ...] [--site-url ...]
  python gerenciar.py imobiliaria dominio <slug> --adicionar <dominio> | --remover <dominio>
  python gerenciar.py imobiliaria ativar|desativar <slug>

  python gerenciar.py migrar [--imobiliaria <slug>]
      Aplica as migrações no banco central e no de todas as imobiliárias (ou
      de uma só). O deploy.sh roda a cada nova versão.

  python gerenciar.py criar-admin [--imobiliaria <slug>]
      Cria (ou redefine a senha de) um administrador da imobiliária. Use no
      primeiro acesso ou se esquecer a senha do administrador.

  python gerenciar.py limpar-arquivos [--imobiliaria <slug>]
      Apaga fotos, vídeos e arquivos enviados que nenhum cadastro usa mais
      (anexo removido ou imóvel excluído), de todas as imobiliárias (ou de
      uma). Pode rodar diariamente (cron).

  python gerenciar.py transcrever [--uma-vez]
      Processa as filas de transcrição dos vídeos das auditorias de todas as
      imobiliárias (roda como serviço no servidor; com --uma-vez, para quando
      as filas esvaziam).

Sem --imobiliaria, o criar-admin usa a IMOBILIARIA_PADRAO do .env.
"""

import argparse
import getpass
import sys

from app.core import imobiliarias
from app.core.config import get_settings
from app.core.database import fabrica
from app.core.errors import RegraNegocio
from app.core.imobiliarias import Imobiliaria, usar
from app.modules import carregar_models


def _imobiliaria(slug: str | None) -> Imobiliaria:
    slug = slug or get_settings().imobiliaria_padrao
    if not slug:
        sys.exit("Informe a imobiliária: --imobiliaria <identificador>.")
    imob = imobiliarias.buscar(slug)
    if imob is None:
        sys.exit(f"Imobiliária '{slug}' não cadastrada (veja: python gerenciar.py imobiliaria listar).")
    return imob


def _alvos(slug: str | None, somente_ativas: bool = True) -> list[Imobiliaria]:
    """A imobiliária informada ou, sem ela, todas."""
    return [_imobiliaria(slug)] if slug else imobiliarias.todas(somente_ativas)


def _central(acao, *args) -> None:
    from app.central import services

    with services.sessao() as db:
        try:
            acao(db, *args)
        except RegraNegocio as e:
            sys.exit(e.mensagem)


# ------------------------------------------------------------ Imobiliárias


def imobiliaria_criar(args: argparse.Namespace) -> None:
    from app.central.services import criar_imobiliaria

    try:
        imob = criar_imobiliaria(
            args.slug, args.nome, args.banco or "", args.site_url or "",
            args.dominio, existente=args.existente,
        )  # fmt: skip
    except RegraNegocio as e:
        sys.exit(e.mensagem)
    print(f"Imobiliária pronta: {imob.nome} ({imob.slug})")
    print(f"  banco: {imob.banco}  ·  arquivos: {imob.pasta_arquivos}")
    if imob.dominios:
        print(f"  domínios: {', '.join(imob.dominios)}  ·  site: {imob.site_url}")
    print(f"  app de gestão: cabeçalho X-Imobiliaria: {imob.slug}")
    if not (args.sem_admin or args.existente):
        print("\nAdministrador da imobiliária:")
        _criar_admin(imob, argparse.Namespace(nome=None, login=None, email=None, senha=None))


def imobiliaria_listar(_: argparse.Namespace) -> None:
    lista = imobiliarias.todas(somente_ativas=False)
    if not lista:
        print("Nenhuma imobiliária cadastrada (python gerenciar.py imobiliaria criar ...).")
    padrao = get_settings().imobiliaria_padrao
    for i in lista:
        marcas = ("" if i.ativa else " [desativada]") + (" [padrão]" if i.slug == padrao else "")
        print(f"{i.slug}{marcas} — {i.nome}")
        print(f"    banco: {i.banco}  ·  site: {i.site_url or '-'}  ·  domínios: {', '.join(i.dominios) or '-'}")


def imobiliaria_editar(args: argparse.Namespace) -> None:
    from app.central.services import editar

    _central(editar, args.slug, args.nome, args.site_url)
    print("Imobiliária atualizada.")


def imobiliaria_dominio(args: argparse.Namespace) -> None:
    from app.central.services import adicionar_dominio, remover_dominio

    if args.adicionar:
        _central(adicionar_dominio, args.slug, args.adicionar)
    else:
        _central(remover_dominio, args.slug, args.remover)
    print("Domínios atualizados (o servidor vê a mudança em até 30 s).")


def imobiliaria_ativa(args: argparse.Namespace) -> None:
    from app.central.services import definir_ativa

    _central(definir_ativa, args.slug, args.ativa)
    print(f"Imobiliária {'ativada' if args.ativa else 'desativada'} (vale em até 30 s).")


# --------------------------------------------------------------- Tarefas


def migrar(args: argparse.Namespace) -> None:
    from app.central import services

    services.migrar_central()
    print("Banco central: ok")
    imobiliarias.limpar_cadastro()
    falhas = 0
    for imob in _alvos(args.imobiliaria, somente_ativas=False):
        try:
            services.migrar(imob)
            print(f"{imob.slug} ({imob.banco}): ok")
        except Exception as e:  # noqa: BLE001 - segue com as demais
            falhas += 1
            print(f"{imob.slug} ({imob.banco}): ERRO {e}", file=sys.stderr)
    if falhas:
        sys.exit(f"Migração falhou em {falhas} banco(s).")


def _criar_admin(imob: Imobiliaria, args: argparse.Namespace) -> None:
    from app.modules.equipe.services import criar_administrador

    nome = args.nome or input("Nome: ").strip()
    login = args.login or input("Usuário (login): ").strip()
    email = args.email if args.email is not None else ""
    senha = args.senha
    if not senha:
        senha = getpass.getpass("Senha (mín. 8 caracteres): ")
        if senha != getpass.getpass("Repita a senha: "):
            sys.exit("As senhas não conferem.")
    with usar(imob), fabrica(imob)() as db:
        try:
            u = criar_administrador(db, nome, login, senha, email)
        except RegraNegocio as e:
            sys.exit(f"{e.mensagem} Tente de novo: python gerenciar.py criar-admin --imobiliaria {imob.slug}")
        print(f"Administrador de {imob.nome} pronto: {u.nome} (usuário: {u.login})")


def criar_admin(args: argparse.Namespace) -> None:
    _criar_admin(_imobiliaria(args.imobiliaria), args)


def limpar_arquivos(args: argparse.Namespace) -> None:
    from app.modules.arquivos.services import limpar_orfaos

    for imob in _alvos(args.imobiliaria):
        with usar(imob), fabrica(imob)() as db:
            print(f"{imob.slug}: arquivos sem uso apagados: {limpar_orfaos(db)}")


def transcrever(args: argparse.Namespace) -> None:
    import logging

    from app.modules.auditoria.transcricao import rodar

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    feitas = rodar(lambda: [(i, fabrica(i)) for i in imobiliarias.todas()], uma_vez=args.uma_vez)
    print(f"Vídeos transcritos: {feitas}")


def main() -> None:
    carregar_models()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="comando", required=True)

    i = sub.add_parser("imobiliaria", help="cadastro das imobiliárias")
    isub = i.add_subparsers(dest="acao", required=True)
    c = isub.add_parser("criar", help="cadastra a imobiliária e cria o banco dela")
    c.add_argument("--slug", required=True, help="identificador curto (ex.: marcelo)")
    c.add_argument("--nome", required=True, help="nome da imobiliária")
    c.add_argument("--banco", help="banco no MySQL (padrão: imob_<slug>)")
    c.add_argument("--site-url", help="endereço público do site (padrão: o 1º domínio)")
    c.add_argument("--dominio", action="append", default=[], help="domínio do site e portais (pode repetir)")
    c.add_argument("--existente", action="store_true", help="usa um banco que já tem dados")
    c.add_argument("--sem-admin", action="store_true", help="não cria o administrador agora")
    c.set_defaults(func=imobiliaria_criar)
    isub.add_parser("listar", help="lista as imobiliárias").set_defaults(func=imobiliaria_listar)
    e = isub.add_parser("editar", help="altera nome ou site")
    e.add_argument("slug")
    e.add_argument("--nome")
    e.add_argument("--site-url")
    e.set_defaults(func=imobiliaria_editar)
    d = isub.add_parser("dominio", help="adiciona ou remove um domínio")
    d.add_argument("slug")
    g = d.add_mutually_exclusive_group(required=True)
    g.add_argument("--adicionar")
    g.add_argument("--remover")
    d.set_defaults(func=imobiliaria_dominio)
    for acao, ativa in (("ativar", True), ("desativar", False)):
        a = isub.add_parser(acao, help=f"{acao} a imobiliária (os dados ficam no banco)")
        a.add_argument("slug")
        a.set_defaults(func=imobiliaria_ativa, ativa=ativa)

    m = sub.add_parser("migrar", help="aplica as migrações em todos os bancos")
    m.add_argument("--imobiliaria", help="só esta imobiliária")
    m.set_defaults(func=migrar)
    c = sub.add_parser("criar-admin", help="cria ou redefine um administrador")
    c.add_argument("--imobiliaria", help="identificador (padrão: IMOBILIARIA_PADRAO)")
    c.add_argument("--nome")
    c.add_argument("--login", help="nome de usuário para entrar")
    c.add_argument("--email", help="opcional, só contato")
    c.add_argument("--senha", help="evite: prefira digitar quando pedido")
    c.set_defaults(func=criar_admin)
    la = sub.add_parser("limpar-arquivos", help="apaga arquivos enviados sem uso")
    la.add_argument("--imobiliaria", help="só esta imobiliária")
    la.set_defaults(func=limpar_arquivos)
    t = sub.add_parser("transcrever", help="processa as filas de transcrição de vídeos")
    t.add_argument("--uma-vez", action="store_true", help="para quando as filas esvaziarem")
    t.set_defaults(func=transcrever)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

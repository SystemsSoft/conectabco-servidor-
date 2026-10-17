#!/usr/bin/env bash
# Atualiza o servidor de produção (EC2) com o código desta pasta:
#   ./deploy.sh [chave.pem] [usuario@host]
# Envia o código (sem .env, chaves, .venv nem arquivos enviados), instala as
# dependências, aplica as migrações do banco e reinicia o serviço.
set -euo pipefail
cd "$(dirname "$0")"
CHAVE=${1:-key-aws.pem}
HOST=${2:-ec2-user@18.191.168.173}
SSH="ssh -i $CHAVE -o BatchMode=yes"

rsync -az --delete -e "$SSH" \
  --exclude .venv --exclude .env --exclude '*.pem' --exclude dados \
  --exclude __pycache__ --exclude .pytest_cache --exclude .git --exclude .idea \
  --exclude .DS_Store --exclude .senha-inicial-admin.txt \
  ./ "$HOST:/opt/marceloimob/"

$SSH "$HOST" 'set -e
  cd /opt/marceloimob
  .venv/bin/pip install -q -r requirements.txt
  sudo -u marceloimob .venv/bin/alembic upgrade head
  sudo systemctl restart marceloimob
  sleep 3
  curl -fsS localhost/saude && echo && curl -fsS localhost/saude/banco && echo'

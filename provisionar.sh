#!/usr/bin/env bash
# Prepara uma instância EC2 nova (Amazon Linux 2023) para receber o servidor:
#   ./provisionar.sh [chave.pem] [usuario@host] [arquivo.env]
# Instala Python 3.12, nginx e cron; cria o usuário do serviço, as pastas, a
# .venv, os serviços (API e fila de transcrição), a limpeza diária de arquivos
# e um swap de 2 GB (a instância tem pouca RAM). Com [arquivo.env], envia o
# .env (só se o servidor ainda não tiver um). Pode rodar de novo: o que já
# existe fica como está. Depois: ./deploy.sh e ./configurar_https.sh.
#
# Layout no servidor:
#   /opt/marceloimob                       código (.env: dono marceloimob, 600)
#   /var/lib/marceloimob/arquivos/<slug>   arquivos enviados de cada imobiliária
#   marceloimob.service                    uvicorn, 2 workers, 127.0.0.1:8000
#   marceloimob-transcricao.service        python gerenciar.py transcrever
#   /etc/nginx/default.d/marceloimob.conf  rotas para o serviço (o
#                                          configurar_https.sh as move p/ snippet)
#   /etc/cron.d/marceloimob                limpeza diária (03:30)
set -euo pipefail
cd "$(dirname "$0")"
CHAVE=${1:-key_aws.pem}
HOST=${2:-ec2-user@44.223.83.147}
ENV_LOCAL=${3:-}
SSH="ssh -i $CHAVE -o BatchMode=yes"

$SSH "$HOST" 'bash -s' <<'REMOTO'
set -euo pipefail

sudo dnf install -y -q python3.12 nginx rsync cronie

# Swap: a instalação das dependências e a transcrição passam de 1 GB.
if ! swapon --show | grep -q /swapfile; then
  sudo dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile >/dev/null
  sudo swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile swap swap defaults 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

# Usuário do serviço (sem login); o código é enviado pelo ec2-user (deploy).
id marceloimob >/dev/null 2>&1 || sudo useradd --system --home-dir /opt/marceloimob --shell /sbin/nologin marceloimob
sudo mkdir -p /opt/marceloimob /var/lib/marceloimob/arquivos
sudo chown "$USER":"$USER" /opt/marceloimob
sudo chown -R marceloimob:marceloimob /var/lib/marceloimob
[ -x /opt/marceloimob/.venv/bin/python ] || python3.12 -m venv /opt/marceloimob/.venv
/opt/marceloimob/.venv/bin/pip install -q --upgrade pip

sudo tee /etc/systemd/system/marceloimob.service >/dev/null <<'UNIT'
[Unit]
Description=Gestão Imobiliária - API
After=network-online.target
Wants=network-online.target

[Service]
User=marceloimob
Group=marceloimob
WorkingDirectory=/opt/marceloimob
ExecStart=/opt/marceloimob/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 2 --proxy-headers --forwarded-allow-ips 127.0.0.1
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT

sudo tee /etc/systemd/system/marceloimob-transcricao.service >/dev/null <<'UNIT'
[Unit]
Description=Gestão Imobiliária - fila de transcrição dos vídeos
After=network-online.target marceloimob.service

[Service]
User=marceloimob
Group=marceloimob
WorkingDirectory=/opt/marceloimob
Environment=HF_HOME=/var/lib/marceloimob/modelos
ExecStart=/opt/marceloimob/.venv/bin/python gerenciar.py transcrever
Nice=10
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable -q marceloimob marceloimob-transcricao

# nginx: tudo para o serviço, repassando o domínio acessado (cada imobiliária
# abre pelo seu domínio) e aceitando os vídeos de até 300 MB.
if ! sudo test -f /etc/nginx/snippets/marceloimob-proxy.conf; then
  sudo tee /etc/nginx/default.d/marceloimob.conf >/dev/null <<'NGINX'
client_max_body_size 300m;
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 300s;
    proxy_request_buffering off;
}
NGINX
fi
sudo nginx -t -q
sudo systemctl enable -q --now nginx
sudo systemctl reload nginx

echo '30 3 * * * marceloimob cd /opt/marceloimob && .venv/bin/python gerenciar.py limpar-arquivos 2>&1 | logger -t marceloimob-limpeza' |
  sudo tee /etc/cron.d/marceloimob >/dev/null
sudo systemctl enable -q --now crond
echo "Servidor preparado."
REMOTO

# .env do servidor (lido só pelo usuário do serviço).
if $SSH "$HOST" 'test -f /opt/marceloimob/.env'; then
  echo ".env: já existe no servidor (mantido)."
elif [ -n "$ENV_LOCAL" ]; then
  $SSH "$HOST" 'sudo install -m 600 -o marceloimob -g marceloimob /dev/stdin /opt/marceloimob/.env' <"$ENV_LOCAL"
  echo ".env: enviado ($ENV_LOCAL)."
else
  echo "Falta o .env: rode de novo com o arquivo como 3º argumento antes do ./deploy.sh."
fi

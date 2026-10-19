#!/usr/bin/env bash
# Liga o HTTPS (Let's Encrypt) no servidor de produção para o domínio:
#   ./configurar_https.sh email@contato [chave.pem] [usuario@host] [dominio]
# Antes: o registro A do domínio deve apontar para o servidor (no domínio
# principal, também o CNAME www) e a porta 443 deve estar liberada no grupo
# de segurança da EC2.
# Pode rodar de novo: reaproveita o certificado se ainda for válido.
set -euo pipefail
cd "$(dirname "$0")"
EMAIL=${1:?informe o e-mail para avisos de expiração do certificado}
CHAVE=${2:-key-aws.pem}
HOST=${3:-ec2-user@18.191.168.173}
DOMINIO=${4:-api.inovacloud.app}
# Domínio principal (exemplo.app) também atende pelo www; subdomínio não.
NOMES=$DOMINIO
[[ $DOMINIO == *.*.* ]] || NOMES="$DOMINIO www.$DOMINIO"
SSH="ssh -i $CHAVE -o BatchMode=yes"

$SSH "$HOST" DOMINIO="$DOMINIO" NOMES="'$NOMES'" EMAIL="$EMAIL" 'bash -s' <<'REMOTO'
set -euo pipefail

# certbot: pacote do sistema ou, se não houver, numa venv própria.
if ! command -v certbot >/dev/null; then
  if ! sudo dnf install -y -q certbot python3-certbot-nginx; then
    sudo python3 -m venv /opt/certbot
    sudo /opt/certbot/bin/pip install -q --upgrade pip certbot certbot-nginx
    sudo ln -sf /opt/certbot/bin/certbot /usr/bin/certbot
  fi
fi

# Bloco do domínio; o certbot acrescenta o 443 e o redirecionamento do 80.
# As rotas (proxy para o serviço, limite de upload) vêm de default.d.
if ! sudo test -f /etc/nginx/conf.d/marceloimob.conf; then
  sudo tee /etc/nginx/conf.d/marceloimob.conf >/dev/null <<NGINX
server {
    listen 80;
    listen [::]:80;
    server_name $NOMES;
    include /etc/nginx/default.d/*.conf;
}
NGINX
fi
sudo nginx -t
sudo systemctl reload nginx

sudo certbot --nginx -n --agree-tos -m "$EMAIL" --redirect --keep-until-expiring \
  --expand -d "${NOMES// /,}"

# Renovação automática (o certificado vale 90 dias).
if systemctl cat certbot-renew.timer >/dev/null 2>&1; then
  sudo systemctl enable --now certbot-renew.timer
else
  echo '17 3,15 * * * root certbot renew -q --deploy-hook "systemctl reload nginx"' |
    sudo tee /etc/cron.d/certbot >/dev/null
fi

# Endereço público: sitemap e cookie seguro da área do inquilino.
cd /opt/marceloimob
if sudo grep -q '^SITE_URL=' .env; then
  sudo sed -i "s|^SITE_URL=.*|SITE_URL=https://$DOMINIO|" .env
else
  echo "SITE_URL=https://$DOMINIO" | sudo tee -a .env >/dev/null
fi
sudo systemctl restart marceloimob
sleep 3
curl -fsS "https://$DOMINIO/saude" && echo
curl -fsS -o /dev/null -w "http://$DOMINIO -> %{http_code} %{redirect_url}\n" "http://$DOMINIO/saude"
REMOTO

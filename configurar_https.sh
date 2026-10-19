#!/usr/bin/env bash
# Liga o HTTPS (Let's Encrypt) no servidor de produção para o domínio:
#   ./configurar_https.sh [email] [chave.pem] [usuario@host] [dominio]
# Sem e-mail, o certificado é emitido sem cadastro de avisos de expiração
# (a renovação é automática). Rodar o script aceita os termos de uso do
# Let's Encrypt em nome de quem o executa.
# Antes: o registro A do domínio deve apontar para o servidor (no domínio
# principal, também o www) e a porta 443 deve estar liberada na EC2.
# Pode rodar de novo: reaproveita o certificado se ainda for válido.
#
# Layout no servidor (já aplicado para api.inovacloud.app):
#   /etc/nginx/snippets/marceloimob-proxy.conf     rotas para o serviço
#   /etc/nginx/conf.d/<arquivo do domínio>.conf     bloco do domínio (+443 do certbot)
#   /etc/nginx/default.d/redireciona-dominio.conf   IP/HTTP -> https://<dominio>
set -euo pipefail
cd "$(dirname "$0")"
EMAIL=${1:-}
CHAVE=${2:-key-aws.pem}
HOST=${3:-ec2-user@18.191.168.173}
DOMINIO=${4:-api.inovacloud.app}
# Domínio principal (exemplo.app) também atende pelo www; subdomínio não.
NOMES=$DOMINIO
[[ $DOMINIO == *.*.* ]] || NOMES="$DOMINIO www.$DOMINIO"
SSH="ssh -i $CHAVE -o BatchMode=yes"

$SSH "$HOST" DOMINIO="$DOMINIO" NOMES="'$NOMES'" EMAIL="'$EMAIL'" 'bash -s' <<'REMOTO'
set -euo pipefail

command -v certbot >/dev/null || sudo dnf install -y -q certbot python3-certbot-nginx

# Rotas para o serviço num snippet (o default.d fica só com o redirecionamento).
sudo mkdir -p /etc/nginx/snippets
if ! sudo test -f /etc/nginx/snippets/marceloimob-proxy.conf; then
  sudo mv /etc/nginx/default.d/marceloimob.conf /etc/nginx/snippets/marceloimob-proxy.conf
fi

# Bloco do domínio, se ainda não existir; o certbot acrescenta o 443.
if ! sudo grep -rqs "server_name .*\b$DOMINIO;" /etc/nginx/conf.d/; then
  sudo tee "/etc/nginx/conf.d/$DOMINIO.conf" >/dev/null <<NGINX
server {
    listen 80;
    listen [::]:80;
    server_name $NOMES;
    include /etc/nginx/snippets/marceloimob-proxy.conf;
}
NGINX
fi

# Acesso pelo IP: o servidor genérico é o padrão da porta 80 e redireciona.
sudo sed -i "0,/listen       80;/s//listen       80 default_server;/; 0,/listen       \[::\]:80;/s//listen       [::]:80 default_server;/" /etc/nginx/nginx.conf
if ! sudo test -f /etc/nginx/default.d/redireciona-dominio.conf; then
  echo "location / { return 301 https://$DOMINIO\$request_uri; }" |
    sudo tee /etc/nginx/default.d/redireciona-dominio.conf >/dev/null
fi
sudo nginx -t
sudo systemctl reload nginx

if [ -n "$EMAIL" ]; then CONTA=(-m "$EMAIL"); else CONTA=(--register-unsafely-without-email); fi
sudo certbot --nginx -n --agree-tos "${CONTA[@]}" --redirect --keep-until-expiring \
  --expand -d "${NOMES// /,}"
sudo systemctl enable --now certbot-renew.timer

# Endereço público: sitemap e cookie seguro da área do inquilino. O .env é
# lido pelo usuário do serviço: dono e permissão voltam ao lugar.
cd /opt/marceloimob
if sudo grep -q '^SITE_URL=' .env; then
  sudo sed -i "s|^SITE_URL=.*|SITE_URL=https://$DOMINIO|" .env
else
  echo "SITE_URL=https://$DOMINIO" | sudo tee -a .env >/dev/null
fi
sudo chown marceloimob:marceloimob .env
sudo chmod 600 .env
sudo systemctl restart marceloimob
sleep 3
curl -fsS "https://$DOMINIO/saude" && echo
curl -fsS -o /dev/null -w "http://$DOMINIO -> %{http_code} %{redirect_url}\n" "http://$DOMINIO/saude"
REMOTO

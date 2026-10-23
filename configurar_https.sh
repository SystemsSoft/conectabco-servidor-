#!/usr/bin/env bash
# Liga o HTTPS (Let's Encrypt) no servidor de produção para o domínio:
#   ./configurar_https.sh [email] [chave.pem] [usuario@host] [dominio] [imobiliaria]
# Com [imobiliaria] (o slug dela), o domínio é o do site de uma imobiliária:
# fica cadastrado para ela e o SITE_URL do servidor não muda.
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
CHAVE=${2:-key_aws.pem}
HOST=${3:-ec2-user@44.223.83.147}
DOMINIO=${4:-api.inovacloud.app}
IMOBILIARIA=${5:-}
# Domínio principal (exemplo.app) também atende pelo www; subdomínio não.
NOMES=$DOMINIO
[[ $DOMINIO == *.*.* ]] || NOMES="$DOMINIO www.$DOMINIO"
SSH="ssh -i $CHAVE -o BatchMode=yes"

# O Let's Encrypt confere o DNS: sem o registro A apontando para o servidor,
# nada é alterado.
IP=${HOST#*@}
if [[ $IP =~ ^[0-9.]+$ ]]; then
  for NOME in $NOMES; do
    if ! dig +short A "$NOME" @8.8.8.8 | grep -qx "$IP"; then
      echo "O DNS de $NOME ainda não aponta para $IP: crie o registro A e tente de novo." >&2
      exit 1
    fi
  done
fi

$SSH "$HOST" DOMINIO="$DOMINIO" NOMES="'$NOMES'" EMAIL="'$EMAIL'" IMOBILIARIA="'$IMOBILIARIA'" 'bash -s' <<'REMOTO'
set -euo pipefail

command -v certbot >/dev/null || sudo dnf install -y -q certbot python3-certbot-nginx

# Rotas para o serviço num snippet (usado pelo bloco de cada domínio).
sudo mkdir -p /etc/nginx/snippets
if ! sudo test -f /etc/nginx/snippets/marceloimob-proxy.conf; then
  sudo cp /etc/nginx/default.d/marceloimob.conf /etc/nginx/snippets/marceloimob-proxy.conf
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

sudo nginx -t
sudo systemctl reload nginx

if [ -n "$EMAIL" ]; then CONTA=(-m "$EMAIL"); else CONTA=(--register-unsafely-without-email); fi
sudo certbot --nginx -n --agree-tos "${CONTA[@]}" --redirect --keep-until-expiring \
  --expand -d "${NOMES// /,}"
sudo systemctl enable --now certbot-renew.timer

# Acesso pelo IP: com o certificado pronto, o servidor genérico (padrão da
# porta 80) deixa de servir a API e redireciona para o domínio.
sudo sed -i "0,/listen       80;/s//listen       80 default_server;/; 0,/listen       \[::\]:80;/s//listen       [::]:80 default_server;/" /etc/nginx/nginx.conf
if ! sudo test -f /etc/nginx/default.d/redireciona-dominio.conf; then
  sudo rm -f /etc/nginx/default.d/marceloimob.conf
  echo "location / { return 301 https://$DOMINIO\$request_uri; }" |
    sudo tee /etc/nginx/default.d/redireciona-dominio.conf >/dev/null
  sudo nginx -t
  sudo systemctl reload nginx
fi

cd /opt/marceloimob
if [ -n "$IMOBILIARIA" ]; then
  # Site da imobiliária: o domínio passa a abri-la (o servidor relê em até 30 s).
  sudo -u marceloimob .venv/bin/python gerenciar.py imobiliaria dominio "$IMOBILIARIA" --adicionar "$DOMINIO"
else
  # Endereço público do servidor: sitemap e cookie seguro das áreas do site.
  # O .env é lido pelo usuário do serviço: dono e permissão voltam ao lugar.
  if sudo grep -q '^SITE_URL=' .env; then
    sudo sed -i "s|^SITE_URL=.*|SITE_URL=https://$DOMINIO|" .env
  else
    echo "SITE_URL=https://$DOMINIO" | sudo tee -a .env >/dev/null
  fi
  sudo chown marceloimob:marceloimob .env
  sudo chmod 600 .env
  sudo systemctl restart marceloimob
fi
sleep 3
curl -fsS "https://$DOMINIO/saude" && echo
curl -fsS -o /dev/null -w "http://$DOMINIO -> %{http_code} %{redirect_url}\n" "http://$DOMINIO/saude"
REMOTO

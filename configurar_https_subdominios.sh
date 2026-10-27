#!/usr/bin/env bash
# HTTPS automático para os subdomínios da associação (imobiliárias sem domínio
# próprio): um certificado curinga *.<domínio da associação>, validado pelo DNS
# da Netlify, e um bloco do nginx que atende todos os subdomínios. Roda uma vez;
# depois, cada imobiliária cadastrada com subdomínio já abre com HTTPS.
#
#   NETLIFY_TOKEN=... ./configurar_https_subdominios.sh [email] [chave.pem] [usuario@host] [dominio]
#
# NETLIFY_TOKEN: token pessoal da Netlify (app.netlify.com → User settings →
# Applications → Personal access tokens). Fica só no servidor, em
# /etc/letsencrypt/netlify-dns.ini (root, 600), para as renovações.
# Antes: registro A "*" do domínio apontando para o servidor (DNS da Netlify).
# Pode rodar de novo: reaproveita o certificado se ainda for válido.
set -euo pipefail
cd "$(dirname "$0")"
EMAIL=${1:-}
CHAVE=${2:-key_aws.pem}
HOST=${3:-ec2-user@44.223.83.147}
DOMINIO=${4:-xn--associaoconectabci-7sb3f.com.br}
SSH="ssh -i $CHAVE -o BatchMode=yes"

if [ -z "${NETLIFY_TOKEN:-}" ]; then
  read -r -s -p "Token pessoal da Netlify: " NETLIFY_TOKEN
  echo
fi
[ -n "$NETLIFY_TOKEN" ] || { echo "Sem o token da Netlify, nada feito." >&2; exit 1; }

# O curinga do DNS precisa apontar para o servidor (um nome qualquer serve de teste).
IP=${HOST#*@}
if [[ $IP =~ ^[0-9.]+$ ]] && ! dig +short A "teste-curinga.$DOMINIO" @8.8.8.8 | grep -qx "$IP"; then
  echo "O registro A \"*\" de $DOMINIO ainda não aponta para $IP: crie na Netlify e tente de novo." >&2
  exit 1
fi

# O token vai pela entrada padrão (não aparece na linha de comando do servidor)
# e fica só para o root.
printf '%s' "$NETLIFY_TOKEN" | $SSH "$HOST" 'sudo install -d -m 700 /etc/letsencrypt &&
  { printf "token="; cat; printf "\n"; } | sudo tee /etc/letsencrypt/netlify-dns.ini >/dev/null &&
  sudo chmod 600 /etc/letsencrypt/netlify-dns.ini'

# Auxiliar de validação: cria e apaga o TXT _acme-challenge na Netlify.
$SSH "$HOST" 'sudo tee /usr/local/bin/netlify-dns-hook >/dev/null && sudo chmod 755 /usr/local/bin/netlify-dns-hook' <<'HOOK'
#!/usr/bin/env python3
"""Hook do certbot (--manual-auth-hook / --manual-cleanup-hook) para validar
pelo DNS da Netlify: `netlify-dns-hook auth` cria o TXT _acme-challenge e
espera propagar; `netlify-dns-hook cleanup` apaga o registro criado."""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

API = "https://api.netlify.com/api/v1"


def token() -> str:
    with open("/etc/letsencrypt/netlify-dns.ini") as f:
        for linha in f:
            if linha.startswith("token="):
                return linha.split("=", 1)[1].strip()
    sys.exit("netlify-dns-hook: token não encontrado")


def chamar(metodo: str, caminho: str, corpo: dict | None = None):
    pedido = urllib.request.Request(
        API + caminho, method=metodo, data=json.dumps(corpo).encode() if corpo else None,
        headers={"Authorization": f"Bearer {token()}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(pedido, timeout=30) as resposta:
        texto = resposta.read()
        return json.loads(texto) if texto else None


def zona(dominio: str) -> str:
    for z in chamar("GET", "/dns_zones"):
        if dominio == z["name"] or dominio.endswith("." + z["name"]):
            return z["id"]
    sys.exit(f"netlify-dns-hook: zona de {dominio} não encontrada na Netlify")


dominio = os.environ["CERTBOT_DOMAIN"]
if sys.argv[1] == "auth":
    registro = chamar("POST", f"/dns_zones/{zona(dominio)}/dns_records", {
        "type": "TXT", "hostname": f"_acme-challenge.{dominio}", "value": os.environ["CERTBOT_VALIDATION"], "ttl": 60,
    })
    print(registro["id"])  # o cleanup recebe em CERTBOT_AUTH_OUTPUT
    time.sleep(45)  # propagação nos servidores de DNS da Netlify
else:
    for registro_id in os.environ.get("CERTBOT_AUTH_OUTPUT", "").split():
        try:
            chamar("DELETE", f"/dns_zones/{zona(dominio)}/dns_records/{registro_id}")
        except Exception as erro:  # noqa: BLE001 - não impede o certificado
            print(f"netlify-dns-hook: não apagou {registro_id}: {erro}", file=sys.stderr)
HOOK

$SSH "$HOST" DOMINIO="$DOMINIO" EMAIL="'$EMAIL'" 'bash -s' <<'REMOTO'
set -euo pipefail
command -v certbot >/dev/null || sudo dnf install -y -q certbot python3-certbot-nginx
if [ -n "$EMAIL" ]; then CONTA=(-m "$EMAIL"); else CONTA=(--register-unsafely-without-email); fi

# Certificado curinga (renova sozinho pelo certbot-renew.timer, com os mesmos hooks).
sudo certbot certonly -n --agree-tos "${CONTA[@]}" --keep-until-expiring \
  --manual --preferred-challenges dns \
  --manual-auth-hook "/usr/local/bin/netlify-dns-hook auth" \
  --manual-cleanup-hook "/usr/local/bin/netlify-dns-hook cleanup" \
  --deploy-hook "systemctl reload nginx" \
  --cert-name "curinga.$DOMINIO" -d "*.$DOMINIO"

# Um bloco para todos os subdomínios (os que têm bloco próprio, como o api,
# continuam no deles: o nginx prefere o nome exato).
sudo tee "/etc/nginx/conf.d/subdominios.$DOMINIO.conf" >/dev/null <<NGINX
server {
    listen 80;
    listen [::]:80;
    server_name *.$DOMINIO;
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name *.$DOMINIO;
    ssl_certificate /etc/letsencrypt/live/curinga.$DOMINIO/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/curinga.$DOMINIO/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;
    include /etc/nginx/snippets/marceloimob-proxy.conf;
}
NGINX
sudo nginx -t
sudo systemctl reload nginx
sudo systemctl enable --now certbot-renew.timer
sleep 2
curl -sS -o /dev/null -w "https://teste-curinga.$DOMINIO/saude -> %{http_code}\n" "https://teste-curinga.$DOMINIO/saude" ||
  echo "(o teste pelo próprio servidor não respondeu; confira de fora)"
REMOTO
echo "Pronto: todo subdomínio de $DOMINIO cadastrado numa imobiliária já abre com HTTPS."

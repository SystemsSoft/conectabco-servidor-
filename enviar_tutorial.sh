#!/usr/bin/env bash
# Envia vídeos tutoriais para o S3 (plataforma/tutoriais/<nome>.mp4), pelo
# servidor, que é onde ficam as chaves da AWS. O nome do arquivo vira o nome
# no bucket; para o vídeo aparecer, ele precisa estar em app/central/tutoriais.py.
#
#   ./enviar_tutorial.sh tutorial/a.mp4 [tutorial/b.mp4 ...]
#
# CHAVE e HOST podem vir do ambiente (padrão: key_aws.pem e o servidor de produção).
set -euo pipefail
cd "$(dirname "$0")"
CHAVE=${CHAVE:-key_aws.pem}
HOST=${HOST:-ec2-user@44.223.83.147}
SSH="ssh -i $CHAVE -o BatchMode=yes"
[ $# -gt 0 ] || { echo "Uso: $0 arquivo.mp4 [...]" >&2; exit 1; }

for arquivo in "$@"; do
  nome=$(basename "$arquivo")
  [[ $nome =~ ^[a-z0-9-]+\.mp4$ ]] || { echo "$nome: use letras minúsculas, números e hífen, terminando em .mp4" >&2; exit 1; }
  echo "Enviando $nome..."
  scp -i "$CHAVE" -o BatchMode=yes "$arquivo" "$HOST:/tmp/$nome"
  $SSH "$HOST" NOME="$nome" 'bash -s' <<'REMOTO'
set -euo pipefail
sudo chown marceloimob "/tmp/$NOME"
cd /opt/marceloimob
sudo -u marceloimob NOME="$NOME" .venv/bin/python - <<'PY'
import os
from pathlib import Path

from app.core.armazenamento import armazenamento, no_s3

assert no_s3(), "ARQUIVOS_ARMAZENAMENTO não é s3"
nome = os.environ["NOME"]
chave = f"plataforma/tutoriais/{nome}"
loja = armazenamento()
loja.gravar(chave, Path(f"/tmp/{nome}"), "video/mp4", {"categoria": "tutorial"})
r = loja.cliente.head_object(Bucket=loja.bucket, Key=chave)
print(f"s3://{loja.bucket}/{chave} · {r['ContentLength']:,} bytes · {r['ContentType']}")
PY
REMOTO
done

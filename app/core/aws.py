"""Clientes da AWS (boto3) com as credenciais do .env: usuário IAM do
servidor (AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY); sem elas, as do ambiente."""

from app.core.config import get_settings


def cliente(servico: str, regiao: str, **config):
    import boto3
    from botocore.config import Config

    s = get_settings()
    opcoes = Config(connect_timeout=5, read_timeout=15, retries={"max_attempts": 2}, **config)
    chaves = {}
    if s.aws_access_key_id:
        chaves = {"aws_access_key_id": s.aws_access_key_id,
                  "aws_secret_access_key": s.aws_secret_access_key}  # fmt: skip
    return boto3.client(servico, region_name=regiao, config=opcoes, **chaves)

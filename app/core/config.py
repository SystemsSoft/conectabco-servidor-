"""Configurações lidas do ambiente / arquivo .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_nome: str = "Marcelo Bonifácio – Gestão Imobiliária"
    versao: str = "1.0.0"
    fuso_horario: str = "America/Sao_Paulo"

    # MySQL (AWS Lightsail)
    db_host: str = ""
    db_port: int = 3306
    db_name: str = "marceloimob"
    db_user: str = ""
    db_password: str = ""
    db_ssl_ca: str = ""

    # Sobrescreve a URL montada a partir de DB_* (usado nos testes).
    database_url: str = ""

    # Assinatura dos tokens de acesso: troque por um valor longo e secreto.
    jwt_secret: str = ""
    token_horas: int = 12

    # Fotos, vídeos e arquivos enviados (pasta no servidor, fora do git).
    arquivos_dir: str = "dados/arquivos"

    # Endereço público do site (sitemap); vazio = o do próprio acesso.
    site_url: str = ""

    cors_origins: str = ""
    host: str = "0.0.0.0"
    port: int = 8000

    @property
    def url_banco(self) -> str | URL:
        if self.database_url:
            return self.database_url
        return URL.create(
            "mysql+pymysql",
            username=self.db_user,
            password=self.db_password,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
            query={"charset": "utf8mb4"},
        )

    @property
    def banco_configurado(self) -> bool:
        return bool(self.database_url or (self.db_host and self.db_user))

    @property
    def lista_cors(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

"""Configurações lidas do ambiente / arquivo .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_nome: str = "Gestão Imobiliária"
    versao: str = "1.0.0"
    fuso_horario: str = "America/Sao_Paulo"

    # MySQL (AWS Lightsail): o mesmo servidor guarda o banco central e o
    # banco de cada imobiliária (o nome de cada um fica no banco central).
    db_host: str = ""
    db_port: int = 3306
    db_user: str = ""
    db_password: str = ""
    db_ssl_ca: str = ""

    # Banco central: cadastro das imobiliárias (banco e domínios de cada uma).
    db_central: str = "conectabco_central"

    # Sobrescrevem as URLs montadas a partir de DB_* (testes e desenvolvimento).
    # Em DATABASE_URL, {banco} vira o banco da imobiliária.
    database_url: str = ""
    central_database_url: str = ""

    # Conexões abertas por imobiliária (cada uma tem o seu pool).
    db_pool: int = 3
    db_pool_extra: int = 5

    # Imobiliária das requisições que não dizem qual é (vazio = exige).
    imobiliaria_padrao: str = ""

    # Assinatura dos tokens de acesso: troque por um valor longo e secreto.
    jwt_secret: str = ""
    token_horas: int = 12

    # Fotos, vídeos e arquivos enviados (pasta no servidor, fora do git);
    # cada imobiliária usa a subpasta com o seu identificador.
    arquivos_dir: str = "dados/arquivos"

    # Build do app de gestão (Flutter web), servido em /gestao.
    gestao_web_dir: str = "web_gestao"

    # Transcrição dos vídeos de auditoria (faster-whisper em CPU).
    transcricao_modelo: str = "small"
    transcricao_threads: int = 2

    # Endereço público deste servidor; vale para a imobiliária sem site próprio.
    site_url: str = ""

    cors_origins: str = ""
    host: str = "0.0.0.0"
    port: int = 8000

    def url_imobiliaria(self, banco: str) -> str | URL:
        if self.database_url:
            return self.database_url.replace("{banco}", banco)
        return self._url_mysql(banco)

    @property
    def url_central(self) -> str | URL:
        return self.central_database_url or self._url_mysql(self.db_central)

    def _url_mysql(self, banco: str) -> URL:
        return URL.create(
            "mysql+pymysql",
            username=self.db_user,
            password=self.db_password,
            host=self.db_host,
            port=self.db_port,
            database=banco,
            query={"charset": "utf8mb4"},
        )

    @property
    def banco_configurado(self) -> bool:
        return bool(self.central_database_url or (self.db_host and self.db_user))

    @property
    def lista_cors(self) -> list[str]:
        # O navegador manda a origem sem a barra final.
        return [o.strip().rstrip("/") for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()

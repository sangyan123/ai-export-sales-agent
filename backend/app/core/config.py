from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Works from backend/ (uv run) and from the repo root (docker / --app-dir).
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    app_secret_key: str
    api_prefix: str = "/api/v1"
    log_level: str = "INFO"

    jwt_secret_key: str | None = None
    jwt_issuer: str = "fastener-ai"
    jwt_audience: str = "fastener-ai-api"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 1_209_600

    database_url: str = "postgresql+asyncpg://fastener:fastener@localhost:5433/fastener_ai"
    migration_database_url: str = (
        "postgresql+psycopg://fastener:fastener@localhost:5433/fastener_ai"
    )
    redis_url: str = "redis://localhost:6379/0"

    s3_endpoint: str | None = None
    s3_bucket: str | None = None
    s3_access_key: str | None = None
    s3_secret_key: str | None = None
    s3_region: str = "us-east-1"
    upload_dir: str = "var/uploads"
    attachment_max_bytes: int = 20 * 1024 * 1024

    llm_provider: str | None = None
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    embedding_model: str | None = None
    sentry_dsn: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

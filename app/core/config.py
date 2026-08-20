from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

SERVICE_ROOT = Path(__file__).resolve().parents[2]


class SettingsConfigurationError(RuntimeError):
    """Raised when the service cannot start with a safe runtime configuration."""


class Settings(BaseSettings):
    app_name: str = Field(
        default="Asianode FastAPI",
        validation_alias=AliasChoices("APP_NAME", "ASIANODE_APP_NAME"),
    )
    environment: str = Field(
        default="development",
        validation_alias=AliasChoices("ENVIRONMENT", "ASIANODE_ENVIRONMENT"),
    )
    debug: bool = Field(
        default=False,
        validation_alias=AliasChoices("DEBUG", "ASIANODE_DEBUG"),
    )
    deepseek_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("DEEPSEEK_API_KEY", "ASIANODE_DEEPSEEK_API_KEY"),
    )
    deepseek_base_url: str = Field(
        default="https://api.deepseek.com/v1",
        validation_alias=AliasChoices("DEEPSEEK_BASE_URL", "ASIANODE_DEEPSEEK_BASE_URL"),
    )
    chat_model: str = Field(
        default="deepseek-chat",
        validation_alias=AliasChoices("CHAT_MODEL", "ASIANODE_CHAT_MODEL"),
    )
    chat_provider_timeout_seconds: float = Field(
        default=60.0,
        ge=1.0,
        le=300.0,
        validation_alias=AliasChoices(
            "CHAT_PROVIDER_TIMEOUT_SECONDS",
            "ASIANODE_CHAT_PROVIDER_TIMEOUT_SECONDS",
        ),
    )
    postgres_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("POSTGRES_URL", "ASIANODE_POSTGRES_URL"),
    )
    redis_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("REDIS_URL", "ASIANODE_REDIS_URL"),
    )
    resumable_stream_ttl_seconds: int = Field(
        default=24 * 60 * 60,
        ge=60,
        validation_alias=AliasChoices(
            "RESUMABLE_STREAM_TTL_SECONDS",
            "ASIANODE_RESUMABLE_STREAM_TTL_SECONDS",
        ),
    )
    cors_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        validation_alias=AliasChoices("CORS_ORIGINS", "ASIANODE_CORS_ORIGINS"),
    )
    auth_required: bool = Field(
        default=False,
        validation_alias=AliasChoices("AUTH_REQUIRED", "ASIANODE_AUTH_REQUIRED"),
    )
    auth_issuer: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "AUTH_ISSUER",
            "ASIANODE_AUTH_ISSUER",
            "LOGTO_ISSUER",
        ),
    )
    auth_audience: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "AUTH_AUDIENCE",
            "ASIANODE_AUTH_AUDIENCE",
            "LOGTO_AUDIENCE",
        ),
    )
    auth_jwks_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "AUTH_JWKS_URL",
            "ASIANODE_AUTH_JWKS_URL",
            "LOGTO_JWKS_URL",
        ),
    )
    auth_algorithms: str = Field(
        default="RS256",
        validation_alias=AliasChoices("AUTH_ALGORITHMS", "ASIANODE_AUTH_ALGORITHMS"),
    )
    auth_secret: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AUTH_SECRET", "ASIANODE_AUTH_SECRET"),
    )
    dev_oidc_internal_secret: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "DEV_OIDC_INTERNAL_SECRET",
            "ASIANODE_DEV_OIDC_INTERNAL_SECRET",
        ),
    )
    dev_direct_auth_secret: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "DEV_DIRECT_AUTH_SECRET",
            "ASIANODE_DEV_DIRECT_AUTH_SECRET",
        ),
    )
    knowledge_grants_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "KNOWLEDGE_GRANTS_ENABLED",
            "ASIANODE_KNOWLEDGE_GRANTS_ENABLED",
        ),
    )
    knowledge_base_entity_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "KNOWLEDGE_BASE_ENTITY_ENABLED",
            "ASIANODE_KNOWLEDGE_BASE_ENTITY_ENABLED",
        ),
    )
    knowledge_ingestion_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "KNOWLEDGE_INGESTION_ENABLED",
            "ASIANODE_KNOWLEDGE_INGESTION_ENABLED",
        ),
    )
    knowledge_storage_dir: str = Field(
        default="storage/knowledge",
        validation_alias=AliasChoices(
            "KNOWLEDGE_STORAGE_DIR",
            "ASIANODE_KNOWLEDGE_STORAGE_DIR",
        ),
    )
    knowledge_storage_provider: str = Field(
        default="local",
        validation_alias=AliasChoices(
            "KNOWLEDGE_STORAGE_PROVIDER",
            "ASIANODE_KNOWLEDGE_STORAGE_PROVIDER",
        ),
    )
    knowledge_s3_bucket: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "KNOWLEDGE_S3_BUCKET",
            "ASIANODE_KNOWLEDGE_S3_BUCKET",
        ),
    )
    knowledge_s3_endpoint_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "KNOWLEDGE_S3_ENDPOINT_URL",
            "ASIANODE_KNOWLEDGE_S3_ENDPOINT_URL",
        ),
    )
    knowledge_s3_region: str = Field(
        default="us-east-1",
        validation_alias=AliasChoices(
            "KNOWLEDGE_S3_REGION",
            "ASIANODE_KNOWLEDGE_S3_REGION",
        ),
    )
    knowledge_s3_access_key_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "KNOWLEDGE_S3_ACCESS_KEY_ID",
            "ASIANODE_KNOWLEDGE_S3_ACCESS_KEY_ID",
        ),
    )
    knowledge_s3_secret_access_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "KNOWLEDGE_S3_SECRET_ACCESS_KEY",
            "ASIANODE_KNOWLEDGE_S3_SECRET_ACCESS_KEY",
        ),
    )
    knowledge_max_file_bytes: int = Field(
        default=25 * 1024 * 1024,
        ge=1,
        validation_alias=AliasChoices(
            "KNOWLEDGE_MAX_FILE_BYTES",
            "ASIANODE_KNOWLEDGE_MAX_FILE_BYTES",
        ),
    )
    knowledge_embeddings_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "KNOWLEDGE_EMBEDDINGS_ENABLED",
            "ASIANODE_KNOWLEDGE_EMBEDDINGS_ENABLED",
        ),
    )
    chat_attachments_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "CHAT_ATTACHMENTS_ENABLED",
            "ASIANODE_CHAT_ATTACHMENTS_ENABLED",
        ),
    )
    attachment_storage_provider: str = Field(
        default="local",
        validation_alias=AliasChoices(
            "ATTACHMENT_STORAGE_PROVIDER",
            "ASIANODE_ATTACHMENT_STORAGE_PROVIDER",
        ),
    )
    attachment_storage_dir: str = Field(
        default="storage/attachments",
        validation_alias=AliasChoices(
            "ATTACHMENT_STORAGE_DIR",
            "ASIANODE_ATTACHMENT_STORAGE_DIR",
        ),
    )
    attachment_max_file_bytes: int = Field(
        default=5 * 1024 * 1024,
        ge=1,
        validation_alias=AliasChoices(
            "ATTACHMENT_MAX_FILE_BYTES",
            "ASIANODE_ATTACHMENT_MAX_FILE_BYTES",
        ),
    )
    attachment_url_ttl_seconds: int = Field(
        default=60 * 60,
        ge=60,
        validation_alias=AliasChoices(
            "ATTACHMENT_URL_TTL_SECONDS",
            "ASIANODE_ATTACHMENT_URL_TTL_SECONDS",
        ),
    )
    attachment_public_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "ATTACHMENT_PUBLIC_BASE_URL",
            "ASIANODE_ATTACHMENT_PUBLIC_BASE_URL",
        ),
    )
    embedding_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("EMBEDDING_API_KEY", "ASIANODE_EMBEDDING_API_KEY"),
    )
    embedding_base_url: str = Field(
        default="https://api.openai.com/v1",
        validation_alias=AliasChoices("EMBEDDING_BASE_URL", "ASIANODE_EMBEDDING_BASE_URL"),
    )
    embedding_model: str = Field(
        default="text-embedding-3-small",
        validation_alias=AliasChoices("EMBEDDING_MODEL", "ASIANODE_EMBEDDING_MODEL"),
    )
    embedding_provider_timeout_seconds: float = Field(
        default=60.0,
        ge=1.0,
        le=300.0,
        validation_alias=AliasChoices(
            "EMBEDDING_PROVIDER_TIMEOUT_SECONDS",
            "ASIANODE_EMBEDDING_PROVIDER_TIMEOUT_SECONDS",
        ),
    )
    rate_limit_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices("RATE_LIMIT_ENABLED", "ASIANODE_RATE_LIMIT_ENABLED"),
    )
    rate_limit_redis_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "RATE_LIMIT_REDIS_ENABLED",
            "ASIANODE_RATE_LIMIT_REDIS_ENABLED",
        ),
    )
    rate_limit_requests: int = Field(
        default=120,
        ge=1,
        validation_alias=AliasChoices("RATE_LIMIT_REQUESTS", "ASIANODE_RATE_LIMIT_REQUESTS"),
    )
    rate_limit_window_seconds: int = Field(
        default=60,
        ge=1,
        validation_alias=AliasChoices(
            "RATE_LIMIT_WINDOW_SECONDS",
            "ASIANODE_RATE_LIMIT_WINDOW_SECONDS",
        ),
    )
    sqladmin_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("SQLADMIN_ENABLED", "ASIANODE_SQLADMIN_ENABLED"),
    )
    sqladmin_username: str = Field(
        default="admin",
        min_length=1,
        validation_alias=AliasChoices("SQLADMIN_USERNAME", "ASIANODE_SQLADMIN_USERNAME"),
    )
    sqladmin_password: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SQLADMIN_PASSWORD", "ASIANODE_SQLADMIN_PASSWORD"),
    )
    sqladmin_secret_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SQLADMIN_SECRET_KEY", "ASIANODE_SQLADMIN_SECRET_KEY"),
    )

    model_config = SettingsConfigDict(
        # Resolve env files from this service repository, not from the process
        # cwd, so the service stays independent of the former outer project.
        env_file=(SERVICE_ROOT / ".env.local", SERVICE_ROOT / ".env"),
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


def validate_runtime_settings(settings: Settings) -> None:
    """Fail fast on unsafe settings outside the local development environment."""
    environment = settings.environment.strip().lower()
    if environment not in {"staging", "production"}:
        return

    errors: list[str] = []
    if settings.debug:
        errors.append("DEBUG must be false")
    if not settings.auth_issuer:
        errors.append("AUTH_ISSUER is required")
    elif not settings.auth_issuer.lower().startswith("https://"):
        errors.append("AUTH_ISSUER must use HTTPS")
    if not settings.auth_audience or not settings.auth_audience.strip():
        errors.append("AUTH_AUDIENCE is required")
    if not settings.auth_secret or len(settings.auth_secret) < 32:
        errors.append("AUTH_SECRET must be at least 32 characters")
    if not settings.auth_algorithms.strip():
        errors.append("AUTH_ALGORITHMS must not be empty")

    origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
    if not origins or "*" in origins:
        errors.append("CORS_ORIGINS must contain explicit origins and cannot include '*'")
    if not settings.rate_limit_enabled:
        errors.append("RATE_LIMIT_ENABLED must be true")
    if settings.sqladmin_enabled:
        errors.append("SQLADMIN_ENABLED must be false outside local development")

    if errors:
        raise SettingsConfigurationError(
            f"Unsafe {environment} configuration: " + "; ".join(errors) + "."
        )

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    nextauth_bridge_secret: str | None = Field(
        default=None,
        validation_alias=AliasChoices(
            "NEXTAUTH_BRIDGE_SECRET",
            "ASIANODE_NEXTAUTH_BRIDGE_SECRET",
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

    model_config = SettingsConfigDict(
        env_file=("../.env.local", ".env"),
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()

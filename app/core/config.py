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

    model_config = SettingsConfigDict(
        env_file=("../.env.local", ".env"),
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()

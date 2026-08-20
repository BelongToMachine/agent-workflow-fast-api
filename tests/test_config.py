import pytest

from app.core.config import (
    Settings,
    SettingsConfigurationError,
    validate_runtime_settings,
)
from app.main import create_app


def _production_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": "production",
        "auth_issuer": "https://issuer.example.com/oidc",
        "auth_audience": "api://asianode",
        "auth_secret": "x" * 32,
        "cors_origins": "https://app.example.com",
        "rate_limit_enabled": True,
    }
    values.update(overrides)
    return Settings(**values)


def test_production_runtime_settings_accept_a_complete_secure_configuration() -> None:
    validate_runtime_settings(_production_settings())


def test_production_runtime_settings_reject_missing_identity_configuration() -> None:
    settings = _production_settings(
        auth_issuer=None,
        auth_audience=None,
        auth_secret=None,
    )

    with pytest.raises(SettingsConfigurationError) as error:
        validate_runtime_settings(settings)

    message = str(error.value)
    assert "AUTH_ISSUER is required" in message
    assert "AUTH_AUDIENCE is required" in message
    assert "AUTH_SECRET must be at least 32 characters" in message


def test_production_runtime_settings_reject_insecure_cors_and_disabled_rate_limit() -> None:
    settings = _production_settings(
        cors_origins="*",
        rate_limit_enabled=False,
    )

    with pytest.raises(SettingsConfigurationError) as error:
        validate_runtime_settings(settings)

    assert "CORS_ORIGINS" in str(error.value)
    assert "RATE_LIMIT_ENABLED" in str(error.value)


def test_app_factory_fails_before_starting_with_unsafe_production_settings(monkeypatch) -> None:
    settings = _production_settings(auth_issuer=None)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    with pytest.raises(SettingsConfigurationError, match="AUTH_ISSUER"):
        create_app()

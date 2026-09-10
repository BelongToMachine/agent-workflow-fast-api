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


def test_default_workspace_role_accepts_employee() -> None:
    settings = Settings(default_workspace_role="employee")

    assert settings.default_workspace_role == "employee"


def test_single_workspace_mode_is_enabled_by_default() -> None:
    settings = Settings()

    assert settings.single_workspace_mode is True


def test_auth_mode_defaults_to_local_session() -> None:
    settings = Settings()

    assert settings.auth_mode == "local_session"


@pytest.mark.parametrize("auth_mode", ["logto", "dual", "local_session"])
def test_auth_mode_accepts_planned_migration_modes(auth_mode: str) -> None:
    settings = Settings(auth_mode=auth_mode)

    assert settings.auth_mode == auth_mode


def test_auth_mode_rejects_unknown_values() -> None:
    with pytest.raises(ValueError):
        Settings(auth_mode="unsupported")


def test_session_timeout_defaults_are_bounded_for_browser_sessions() -> None:
    settings = Settings()

    assert settings.session_idle_timeout_seconds == 12 * 60 * 60
    assert settings.session_absolute_timeout_seconds == 3 * 24 * 60 * 60
    assert settings.session_touch_interval_seconds == 5 * 60


def test_production_runtime_settings_reject_missing_identity_configuration() -> None:
    settings = _production_settings(
        auth_mode="logto",
        auth_issuer=None,
        auth_audience=None,
        auth_secret=None,
    )

    with pytest.raises(SettingsConfigurationError) as error:
        validate_runtime_settings(settings)

    message = str(error.value)
    assert "AUTH_ISSUER is required for Logto/dual mode" in message
    assert "AUTH_AUDIENCE is required for Logto/dual mode" in message
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
    settings = _production_settings(auth_mode="logto", auth_issuer=None)
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    with pytest.raises(SettingsConfigurationError, match="AUTH_ISSUER"):
        create_app()


def test_local_session_production_does_not_require_logto_configuration() -> None:
    settings = _production_settings(
        auth_mode="local_session",
        auth_issuer=None,
        auth_audience=None,
        auth_algorithms="",
    )

    validate_runtime_settings(settings)

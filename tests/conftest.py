"""Keep the unit-test application independent from a developer's .env.local."""

import os


def pytest_configure() -> None:
    """Use deterministic local defaults before test modules import app.main."""

    from app.core.config import Settings

    Settings.model_config["env_file"] = None
    setting_names = {
        name.lower()
        for field_name, field in Settings.model_fields.items()
        for name in (field_name, *field.validation_alias.choices)
    }
    for name in list(os.environ):
        if name.lower() in setting_names:
            del os.environ[name]

    os.environ["ENVIRONMENT"] = "development"
    os.environ["AUTH_REQUIRED"] = "false"
    os.environ["AUTH_ALGORITHMS"] = "RS256"

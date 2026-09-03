"""Keep the unit-test application independent from a developer's .env.local."""

import os


def pytest_configure() -> None:
    """Use deterministic local defaults before test modules import app.main."""

    os.environ["ENVIRONMENT"] = "development"
    os.environ["AUTH_REQUIRED"] = "false"
    os.environ["AUTH_ALGORITHMS"] = "RS256"

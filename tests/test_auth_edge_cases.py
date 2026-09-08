import pytest

from app.core.auth import AuthTokenError, _auth_is_required, _principal_from_claims
from app.core.auth import _verify_dev_direct_token as verify_dev_token
from app.core.config import Settings
from app.db.migration_utils import migration_apply_error
from app.services.attachments import verify_local_attachment_token


@pytest.mark.parametrize("token", ["dev.中文.signature", "dev.payload.中文"])
def test_malformed_dev_tokens_are_rejected_without_server_error(token) -> None:
    assert verify_dev_token(token, Settings(environment="development")) is None


def test_malformed_attachment_token_is_rejected_without_server_error() -> None:
    assert verify_local_attachment_token(Settings(auth_secret="test"), "中文.signature") is None


def test_oversized_oidc_subject_is_an_auth_error() -> None:
    with pytest.raises(AuthTokenError):
        _principal_from_claims({"sub": "x" * 256, "iss": "https://issuer.example.com"})


@pytest.mark.parametrize("environment", [" Production ", " STAGING "])
def test_padded_environment_keeps_auth_and_migration_guards(environment) -> None:
    settings = Settings(environment=environment, postgres_url="postgresql://localhost/test")
    assert _auth_is_required(settings)
    assert "staging/production" in migration_apply_error(settings)

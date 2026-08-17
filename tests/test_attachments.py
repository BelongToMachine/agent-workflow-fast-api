from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import app
from app.services.attachments import (
    create_local_attachment_token,
    verify_local_attachment_token,
)

client = TestClient(app)


@pytest.fixture
def enabled_local_attachments(tmp_path):
    settings = Settings(
        attachment_storage_dir=str(tmp_path),
        auth_secret="attachment-secret",
        chat_attachments_enabled=True,
        environment="development",
    )
    app.dependency_overrides[get_settings] = lambda: settings
    yield settings
    app.dependency_overrides.pop(get_settings, None)


def test_attachment_upload_returns_legacy_compatible_shape_and_signed_url(
    enabled_local_attachments: Settings,
) -> None:
    response = client.post(
        "/api/v1/files/upload",
        params={"workspace_id": "00000000-0000-0000-0000-000000000001"},
        files={"file": ("../brief image.png", b"png-bytes", "image/png")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["contentType"] == "image/png"
    assert payload["pathname"].endswith("brief_image.png")

    attachment_url = urlsplit(payload["url"])
    downloaded = client.get(attachment_url.path)
    assert downloaded.status_code == 200
    assert downloaded.content == b"png-bytes"
    assert downloaded.headers["content-type"] == "image/png"


def test_attachment_download_rejects_a_tampered_signature(
    enabled_local_attachments: Settings,
) -> None:
    token = create_local_attachment_token(
        enabled_local_attachments,
        content_type="image/png",
        filename="brief.png",
        storage_key="workspace/user/brief.png",
    )

    response = client.get(f"/api/v1/files/attachments/{token}tampered")

    assert response.status_code == 404
    assert verify_local_attachment_token(
        enabled_local_attachments,
        f"{token}tampered",
    ) is None


def test_attachment_upload_rejects_unsupported_types(
    enabled_local_attachments: Settings,
) -> None:
    response = client.post(
        "/api/v1/files/upload",
        params={"workspace_id": "00000000-0000-0000-0000-000000000001"},
        files={"file": ("brief.pdf", b"pdf", "application/pdf")},
    )

    assert response.status_code == 415
    assert response.json()["error"] == "File type should be JPEG or PNG."


def test_attachment_upload_is_disabled_by_default() -> None:
    settings = Settings(environment="development", chat_attachments_enabled=False)
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        response = client.post(
            "/api/v1/files/upload",
            params={"workspace_id": "00000000-0000-0000-0000-000000000001"},
            files={"file": ("brief.png", b"png", "image/png")},
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 409
    assert response.json()["code"] == "chat_attachments:disabled"

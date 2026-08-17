from urllib.parse import urlsplit
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.main import app
from app.services.attachments import (
    attachment_content_matches_type,
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
    content = b"\x89PNG\r\n\x1a\npng-bytes"
    response = client.post(
        "/api/v1/files/upload",
        params={"workspace_id": "00000000-0000-0000-0000-000000000001"},
        files={"file": ("../brief image.png", content, "image/png")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["contentType"] == "image/png"
    assert payload["pathname"].endswith("brief_image.png")

    attachment_url = urlsplit(payload["url"])
    downloaded = client.get(attachment_url.path)
    assert downloaded.status_code == 200
    assert downloaded.content == content
    assert downloaded.headers["content-type"] == "image/png"


def test_attachment_upload_passes_workspace_to_permission_and_storage_boundary(
    enabled_local_attachments: Settings,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    async def fake_require_workspace_permission(current_user, workspace_id, permission):
        captured.update(
            {
                "user_id": current_user.user_id,
                "workspace_id": workspace_id,
                "permission": permission,
            }
        )

    monkeypatch.setattr(
        "app.api.routes.attachments.require_workspace_permission",
        fake_require_workspace_permission,
    )

    workspace_id = "00000000-0000-0000-0000-000000000001"
    response = client.post(
        "/api/v1/files/upload",
        params={"workspace_id": workspace_id},
        files={"file": ("brief.png", b"\x89PNG\r\n\x1a\ncontent", "image/png")},
    )

    assert response.status_code == 200
    assert captured == {
        "user_id": "development-user",
        "workspace_id": UUID(workspace_id),
        "permission": "document.write",
    }
    assert response.json()["pathname"].startswith(
        f"{workspace_id}/development-user/"
    )


def test_attachment_content_signature_matches_declared_type() -> None:
    assert attachment_content_matches_type("image/png", b"\x89PNG\r\n\x1a\nrest")
    assert attachment_content_matches_type("image/jpeg", b"\xff\xd8\xff\xe0rest")
    assert not attachment_content_matches_type("image/png", b"not-a-png")
    assert not attachment_content_matches_type("image/gif", b"GIF89a")


def test_attachment_upload_rejects_mismatched_content(
    enabled_local_attachments: Settings,
) -> None:
    response = client.post(
        "/api/v1/files/upload",
        params={"workspace_id": "00000000-0000-0000-0000-000000000001"},
        files={"file": ("brief.png", b"not-a-png", "image/png")},
    )

    assert response.status_code == 415
    assert response.json()["code"] == "attachments:invalid_content"


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

import base64
import hashlib
import hmac
import json
import re
import time
from uuid import UUID, uuid4

from app.core.config import Settings
from app.services.storage import (
    LocalKnowledgeStorage,
    S3KnowledgeStorage,
    StorageConfigurationError,
)

SUPPORTED_ATTACHMENT_TYPES = frozenset({"image/jpeg", "image/png"})
ATTACHMENT_SIGNATURES = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
}
SAFE_FILENAME_PATTERN = re.compile(r"[^a-zA-Z0-9._-]+")


def safe_attachment_filename(filename: str) -> str:
    candidate = SAFE_FILENAME_PATTERN.sub("_", filename).strip("._")
    return (candidate or "attachment")[:160]


def attachment_content_matches_type(content_type: str, content: bytes) -> bool:
    return any(
        content.startswith(signature)
        for signature in ATTACHMENT_SIGNATURES.get(content_type, ())
    )


def build_attachment_storage(settings: Settings) -> LocalKnowledgeStorage | S3KnowledgeStorage:
    if settings.attachment_storage_provider == "local":
        return LocalKnowledgeStorage(settings.attachment_storage_dir)
    if settings.attachment_storage_provider == "s3":
        if not settings.knowledge_s3_bucket:
            raise StorageConfigurationError(
                "KNOWLEDGE_S3_BUCKET is required for S3 chat attachments."
            )
        return S3KnowledgeStorage(
            access_key_id=settings.knowledge_s3_access_key_id,
            bucket=settings.knowledge_s3_bucket,
            endpoint_url=settings.knowledge_s3_endpoint_url,
            region=settings.knowledge_s3_region,
            secret_access_key=settings.knowledge_s3_secret_access_key,
        )
    raise StorageConfigurationError(
        "ATTACHMENT_STORAGE_PROVIDER must be either local or s3."
    )


def build_attachment_storage_key(
    workspace_id: UUID,
    user_id: str,
    filename: str,
) -> str:
    safe_name = safe_attachment_filename(filename)
    safe_user_id = safe_attachment_filename(user_id)
    return f"{workspace_id}/{safe_user_id}/{uuid4()}-{safe_name}"


def _signing_secret(settings: Settings) -> str | None:
    return settings.nextauth_bridge_secret or settings.auth_secret


def create_local_attachment_token(
    settings: Settings,
    *,
    content_type: str,
    filename: str,
    storage_key: str,
) -> str:
    secret = _signing_secret(settings)
    if not secret:
        raise StorageConfigurationError(
            "AUTH_SECRET or NEXTAUTH_BRIDGE_SECRET is required for local attachment URLs."
        )
    payload = {
        "contentType": content_type,
        "exp": int(time.time()) + settings.attachment_url_ttl_seconds,
        "name": safe_attachment_filename(filename),
        "storageKey": storage_key,
    }
    encoded_payload = base64.urlsafe_b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).rstrip(b"=").decode("ascii")
    signature = hmac.new(
        secret.encode("utf-8"),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    return f"{encoded_payload}.{encoded_signature}"


def verify_local_attachment_token(
    settings: Settings,
    token: str,
) -> dict[str, str] | None:
    secret = _signing_secret(settings)
    if not secret or "." not in token:
        return None
    encoded_payload, encoded_signature = token.split(".", 1)
    expected_signature = hmac.new(
        secret.encode("utf-8"),
        encoded_payload.encode("ascii"),
        hashlib.sha256,
    ).digest()
    try:
        actual_signature = base64.urlsafe_b64decode(
            encoded_signature + "=" * (-len(encoded_signature) % 4)
        )
        payload = json.loads(
            base64.urlsafe_b64decode(
                encoded_payload + "=" * (-len(encoded_payload) % 4)
            ).decode("utf-8")
        )
    except (TypeError, ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not hmac.compare_digest(actual_signature, expected_signature):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        expires_at = int(payload.get("exp", 0))
    except (TypeError, ValueError):
        return None
    if expires_at < int(time.time()):
        return None
    storage_key = payload.get("storageKey")
    content_type = payload.get("contentType")
    filename = payload.get("name")
    if not all(isinstance(value, str) and value for value in (storage_key, content_type, filename)):
        return None
    return {
        "contentType": content_type,
        "name": filename,
        "storageKey": storage_key,
    }

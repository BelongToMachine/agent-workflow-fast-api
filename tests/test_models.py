from fastapi.testclient import TestClient

from app.api.routes.models import (
    DEFAULT_MODEL_ID,
    MODEL_CAPABILITIES,
    ModelCapabilities,
    resolve_chat_model,
)
from app.main import app

client = TestClient(app)


def test_model_capabilities_preserve_existing_web_shape() -> None:
    capabilities = MODEL_CAPABILITIES["deepseek-chat"]

    assert isinstance(capabilities, ModelCapabilities)
    assert capabilities.model_dump() == {
        "reasoning": False,
        "tools": True,
        "vision": False,
    }


def test_model_capabilities_are_public_and_do_not_require_authentication() -> None:
    response = client.get("/api/v1/models")

    assert response.status_code == 200
    assert response.json() == {
        "deepseek-chat": {"reasoning": False, "tools": True, "vision": False}
    }


def test_chat_model_resolution_rejects_unlisted_client_and_configuration_values() -> None:
    assert resolve_chat_model("untrusted-provider/model", "deepseek-chat") == DEFAULT_MODEL_ID
    assert resolve_chat_model(None, "untrusted-provider/model") == DEFAULT_MODEL_ID
    assert resolve_chat_model("deepseek-chat", "untrusted-provider/model") == "deepseek-chat"

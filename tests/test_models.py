from fastapi.testclient import TestClient

from app.api.routes.models import MODEL_CAPABILITIES, ModelCapabilities
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

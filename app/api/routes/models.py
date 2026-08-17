from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["models"])
DEFAULT_MODEL_ID = "deepseek-chat"


class ModelCapabilities(BaseModel):
    tools: bool
    vision: bool
    reasoning: bool


MODEL_CAPABILITIES = {
    DEFAULT_MODEL_ID: ModelCapabilities(
        reasoning=False,
        tools=True,
        vision=False,
    )
}


def is_supported_model(model_id: str | None) -> bool:
    return isinstance(model_id, str) and model_id in MODEL_CAPABILITIES


def resolve_chat_model(requested_model: str | None, configured_model: str | None) -> str:
    if is_supported_model(requested_model):
        return requested_model
    if is_supported_model(configured_model):
        return configured_model
    return DEFAULT_MODEL_ID


@router.get("/models", response_model=dict[str, ModelCapabilities])
async def get_model_capabilities() -> dict[str, ModelCapabilities]:
    return MODEL_CAPABILITIES

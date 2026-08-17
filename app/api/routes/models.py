from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["models"])


class ModelCapabilities(BaseModel):
    tools: bool
    vision: bool
    reasoning: bool


MODEL_CAPABILITIES = {
    "deepseek-chat": ModelCapabilities(
        reasoning=False,
        tools=True,
        vision=False,
    )
}


@router.get("/models", response_model=dict[str, ModelCapabilities])
async def get_model_capabilities() -> dict[str, ModelCapabilities]:
    return MODEL_CAPABILITIES

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

BusinessValueType = Literal["string", "decimal", "currency"]


class PersistenceMapping(BaseModel):
    """Physical storage metadata kept out of the model-facing contract."""

    model_config = ConfigDict(extra="forbid")

    column: str = Field(min_length=1)
    table: str = Field(min_length=1)


class BusinessField(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    aliases: list[str] = Field(default_factory=list)
    description: str = Field(min_length=1)
    evidence_required: bool = Field(default=True, alias="evidenceRequired")
    persistence: PersistenceMapping
    required_for_proposal: bool = Field(default=False, alias="requiredForProposal")
    type: BusinessValueType


class BusinessEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1)
    fields: dict[str, BusinessField] = Field(min_length=1)


class BusinessProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1)
    entities: dict[str, BusinessEntity] = Field(min_length=1)
    profile: str = Field(min_length=1)
    version: str = Field(min_length=1)

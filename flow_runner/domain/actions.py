from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ActionSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    capability: str = Field(min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)

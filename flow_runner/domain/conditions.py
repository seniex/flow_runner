from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class LeafCondition(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["leaf"] = "leaf"
    id: str = Field(min_length=1)
    capability: str = Field(min_length=1)
    config: dict[str, Any] = Field(default_factory=dict)


class ConditionGroup(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["group"] = "group"
    id: str = Field(min_length=1)
    operator: Literal["and", "or", "not"]
    children: list[ConditionNode] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_not_arity(self) -> ConditionGroup:
        if self.operator == "not" and len(self.children) != 1:
            raise ValueError("NOT condition group requires exactly one child")
        child_ids = [child.id for child in self.children]
        if len(child_ids) != len(set(child_ids)):
            raise ValueError("condition child ids must be unique within a group")
        return self


ConditionNode = Annotated[LeafCondition | ConditionGroup, Field(discriminator="kind")]

ConditionGroup.model_rebuild()


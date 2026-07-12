from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from flow_runner.domain.enums import ConditionOutcome, StepOutcome


class ConditionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    node_id: str
    outcome: ConditionOutcome
    text: str | None = None
    position: tuple[int, int] | None = None
    bounds: tuple[int, int, int, int] | None = None
    confidence: float | None = None
    provider_data: dict[str, Any] = Field(default_factory=dict)
    children: dict[str, ConditionResult] = Field(default_factory=dict)
    group_operator: Literal["and", "or", "not"] | None = None

    @property
    def primary(self) -> ConditionResult | None:
        if self.group_operator is None:
            return self if self.outcome is ConditionOutcome.MATCH else None
        if self.group_operator != "or":
            return None
        matches = [child.primary for child in self.children.values()]
        unambiguous = [match for match in matches if match is not None]
        return unambiguous[0] if len(unambiguous) == 1 else None

    @classmethod
    def and_group(
        cls,
        node_id: str,
        children: Iterable[ConditionResult],
    ) -> ConditionResult:
        child_map = cls._child_map(children)
        outcomes = [child.outcome for child in child_map.values()]
        if any(outcome is ConditionOutcome.ERROR for outcome in outcomes):
            outcome = ConditionOutcome.ERROR
        elif all(outcome is ConditionOutcome.MATCH for outcome in outcomes):
            outcome = ConditionOutcome.MATCH
        else:
            outcome = ConditionOutcome.NO_MATCH
        return cls(
            node_id=node_id,
            outcome=outcome,
            children=child_map,
            group_operator="and",
        )

    @classmethod
    def or_group(
        cls,
        node_id: str,
        children: Iterable[ConditionResult],
    ) -> ConditionResult:
        child_map = cls._child_map(children)
        outcomes = [child.outcome for child in child_map.values()]
        if any(outcome is ConditionOutcome.MATCH for outcome in outcomes):
            outcome = ConditionOutcome.MATCH
        elif any(outcome is ConditionOutcome.ERROR for outcome in outcomes):
            outcome = ConditionOutcome.ERROR
        else:
            outcome = ConditionOutcome.NO_MATCH
        return cls(
            node_id=node_id,
            outcome=outcome,
            children=child_map,
            group_operator="or",
        )

    @classmethod
    def not_group(cls, node_id: str, child: ConditionResult) -> ConditionResult:
        if child.outcome is ConditionOutcome.MATCH:
            outcome = ConditionOutcome.NO_MATCH
        elif child.outcome is ConditionOutcome.NO_MATCH:
            outcome = ConditionOutcome.MATCH
        else:
            outcome = ConditionOutcome.ERROR
        return cls(
            node_id=node_id,
            outcome=outcome,
            children={child.node_id: child},
            group_operator="not",
        )

    @staticmethod
    def _child_map(children: Iterable[ConditionResult]) -> dict[str, ConditionResult]:
        child_map: dict[str, ConditionResult] = {}
        for child in children:
            if child.node_id in child_map:
                raise ValueError(f"duplicate condition result node_id: {child.node_id}")
            child_map[child.node_id] = child
        if not child_map:
            raise ValueError("condition group requires at least one child")
        return child_map


class ActionResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: StepOutcome
    value: Any = None
    provider_data: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class StepResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: StepOutcome
    condition_result: ConditionResult | None = None
    action_results: tuple[ActionResult, ...] = ()
    error: str | None = None

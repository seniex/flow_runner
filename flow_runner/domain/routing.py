from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from flow_runner.domain.enums import StepOutcome


class RouteTargetKind(StrEnum):
    NEXT_STEP = "next_step"
    JUMP_WORKFLOW = "jump_workflow"
    CALL_WORKFLOW = "call_workflow"
    RETURN = "return"
    END = "end"


class ComparisonOperator(StrEnum):
    EQ = "eq"
    NE = "ne"
    LT = "lt"
    LE = "le"
    GT = "gt"
    GE = "ge"


class RoutePredicate(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: Literal[
        "task_variable",
        "workflow_variable",
        "workflow_count",
        "step_count",
    ]
    key: str
    operator: ComparisonOperator
    expected: Any

    @classmethod
    def workflow_count(
        cls,
        workflow_id: UUID,
        operator: ComparisonOperator,
        expected: int,
    ) -> RoutePredicate:
        return cls(
            source="workflow_count",
            key=str(workflow_id),
            operator=operator,
            expected=expected,
        )

    @classmethod
    def step_count(
        cls,
        step_id: UUID,
        operator: ComparisonOperator,
        expected: int,
    ) -> RoutePredicate:
        return cls(
            source="step_count",
            key=str(step_id),
            operator=operator,
            expected=expected,
        )

    @classmethod
    def task_variable(
        cls,
        name: str,
        operator: ComparisonOperator,
        expected: Any,
    ) -> RoutePredicate:
        return cls(
            source="task_variable",
            key=name,
            operator=operator,
            expected=expected,
        )


class RouteTarget(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: RouteTargetKind
    step_id: UUID | None = None
    workflow_id: UUID | None = None

    @classmethod
    def next_step(cls, step_id: UUID) -> RouteTarget:
        return cls(kind=RouteTargetKind.NEXT_STEP, step_id=step_id)

    @classmethod
    def jump_workflow(cls, workflow_id: UUID) -> RouteTarget:
        return cls(kind=RouteTargetKind.JUMP_WORKFLOW, workflow_id=workflow_id)

    @classmethod
    def call_workflow(cls, workflow_id: UUID) -> RouteTarget:
        return cls(kind=RouteTargetKind.CALL_WORKFLOW, workflow_id=workflow_id)

    @classmethod
    def return_to_caller(cls) -> RouteTarget:
        return cls(kind=RouteTargetKind.RETURN)

    @classmethod
    def end(cls) -> RouteTarget:
        return cls(kind=RouteTargetKind.END)

    @model_validator(mode="after")
    def validate_target_fields(self) -> RouteTarget:
        if self.kind is RouteTargetKind.NEXT_STEP:
            if self.step_id is None or self.workflow_id is not None:
                raise ValueError("next_step target requires only step_id")
        elif self.kind in {RouteTargetKind.JUMP_WORKFLOW, RouteTargetKind.CALL_WORKFLOW}:
            if self.workflow_id is None or self.step_id is not None:
                raise ValueError(f"{self.kind.value} target requires only workflow_id")
        elif self.step_id is not None or self.workflow_id is not None:
            raise ValueError(f"{self.kind.value} target cannot contain ids")
        return self


class RouteRule(BaseModel):
    model_config = ConfigDict(frozen=True)

    outcome: StepOutcome
    predicate: RoutePredicate | None = None
    target: RouteTarget

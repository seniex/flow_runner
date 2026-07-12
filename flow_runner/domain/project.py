from __future__ import annotations

from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from flow_runner.domain.actions import ActionSpec
from flow_runner.domain.conditions import ConditionNode
from flow_runner.domain.policies import ActionPolicy, ConditionPolicy
from flow_runner.domain.routing import RouteRule, RouteTargetKind


class AutomationStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1)
    enabled: bool = True
    condition: ConditionNode | None = None
    actions: list[ActionSpec] = Field(default_factory=list)
    condition_policy: ConditionPolicy = Field(default_factory=ConditionPolicy)
    action_policy: ActionPolicy = Field(default_factory=ActionPolicy)
    routes: list[RouteRule] = Field(default_factory=list)

    @field_validator("condition", mode="before")
    @classmethod
    def infer_condition_kinds(cls, value: Any) -> Any:
        return _infer_condition_kind(value)


class Workflow(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1)
    steps: list[AutomationStep] = Field(default_factory=list)


class FlowGroup(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1)
    workflows: list[Workflow] = Field(default_factory=list)


class Project(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal[1] = 1
    id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1)
    groups: list[FlowGroup] = Field(default_factory=list)
    settings: dict[str, Any] = Field(default_factory=dict)

    def validate_references(self) -> list[str]:
        errors: list[str] = []
        workflows = [workflow for group in self.groups for workflow in group.workflows]
        workflow_counts = self._counts(workflow.id for workflow in workflows)
        for workflow_id, count in workflow_counts.items():
            if count > 1:
                errors.append(f"duplicate workflow id {workflow_id}")

        step_counts = self._counts(step.id for workflow in workflows for step in workflow.steps)
        for step_id, count in step_counts.items():
            if count > 1:
                errors.append(f"duplicate step id {step_id}")

        workflow_ids = set(workflow_counts)
        for workflow in workflows:
            own_step_ids = {step.id for step in workflow.steps}
            for step in workflow.steps:
                for route in step.routes:
                    target = route.target
                    if (
                        target.kind
                        in {RouteTargetKind.JUMP_WORKFLOW, RouteTargetKind.CALL_WORKFLOW}
                        and target.workflow_id not in workflow_ids
                    ):
                        errors.append(
                            f"workflow '{workflow.name}' step '{step.name}' references missing "
                            f"workflow {target.workflow_id}"
                        )
                    elif (
                        target.kind is RouteTargetKind.NEXT_STEP
                        and target.step_id not in own_step_ids
                    ):
                        errors.append(
                            f"workflow '{workflow.name}' step '{step.name}' references missing "
                            f"step {target.step_id}"
                        )
        return errors

    @staticmethod
    def _counts(values: Any) -> dict[UUID, int]:
        counts: dict[UUID, int] = {}
        for value in values:
            counts[value] = counts.get(value, 0) + 1
        return counts


def _infer_condition_kind(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    normalized = dict(value)
    if "kind" not in normalized:
        normalized["kind"] = "group" if "operator" in normalized else "leaf"
    if normalized["kind"] == "group" and "children" in normalized:
        normalized["children"] = [_infer_condition_kind(child) for child in normalized["children"]]
    return normalized

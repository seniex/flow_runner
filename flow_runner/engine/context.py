from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from flow_runner.domain.results import ConditionResult


@dataclass(frozen=True, slots=True)
class CallFrame:
    workflow_id: UUID
    next_step_id: UUID | None


@dataclass(slots=True)
class TaskContext:
    task_variables: dict[str, Any] = field(default_factory=dict)
    persistent_variables: dict[str, Any] = field(default_factory=dict)
    call_stack: list[CallFrame] = field(default_factory=list)


@dataclass(slots=True)
class WorkflowContext:
    task: TaskContext = field(default_factory=TaskContext)
    workflow_variables: dict[str, Any] = field(default_factory=dict)
    workflow_counts: dict[UUID, int] = field(default_factory=dict)
    step_counts: dict[UUID, int] = field(default_factory=dict)


@dataclass(slots=True)
class StepContext:
    result: ConditionResult | None = None
    task_variables: dict[str, Any] = field(default_factory=dict)
    workflow_variables: dict[str, Any] = field(default_factory=dict)
    persistent_variables: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_workflow(cls, workflow: WorkflowContext) -> StepContext:
        return cls(
            task_variables=workflow.task.task_variables,
            workflow_variables=workflow.workflow_variables,
            persistent_variables=workflow.task.persistent_variables,
        )

    def clear_result(self) -> None:
        self.result = None

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import UUID

from flow_runner.domain.enums import StepOutcome
from flow_runner.domain.errors import RoutingError
from flow_runner.domain.project import AutomationStep, Project, Workflow
from flow_runner.domain.results import StepResult
from flow_runner.domain.routing import (
    ComparisonOperator,
    RoutePredicate,
    RouteRule,
    RouteTargetKind,
)
from flow_runner.engine.context import CallFrame, TaskContext


class StepExecutorLike(Protocol):
    async def execute(self, step: AutomationStep) -> StepResult: ...


TransitionObserver = Callable[
    [str, Workflow, AutomationStep, StepResult | None, RouteRule | None],
    None,
]


@dataclass(frozen=True, slots=True)
class WorkflowTrace:
    workflow_names: tuple[str, ...]
    step_names: tuple[str, ...]
    terminal_outcome: StepOutcome


class WorkflowExecutor:
    def __init__(
        self,
        project: Project,
        step_executor: StepExecutorLike,
        *,
        transition_limit: int = 10_000,
        task_context: TaskContext | None = None,
        observer: TransitionObserver | None = None,
    ) -> None:
        if transition_limit <= 0:
            raise ValueError("transition_limit must be positive")
        reference_errors = project.validate_references()
        if reference_errors:
            raise RoutingError("; ".join(reference_errors))
        self.project = project
        self.step_executor = step_executor
        self.transition_limit = transition_limit
        self.task_context = task_context or TaskContext()
        self.observer = observer
        self._workflows = {
            workflow.id: workflow for group in project.groups for workflow in group.workflows
        }
        self._workflow_counts: dict[UUID, int] = {}
        self._step_counts: dict[UUID, int] = {}
        self._workflow_variables: dict[UUID, dict[str, Any]] = {}

    async def run(self, entry_workflow_id: UUID) -> WorkflowTrace:
        workflow_names: list[str] = []
        step_names: list[str] = []
        transitions = 0
        workflow, step = self._enter_workflow(entry_workflow_id, workflow_names)
        terminal_outcome = StepOutcome.SUCCESS

        while step is not None:
            transitions += 1
            if transitions > self.transition_limit:
                raise RoutingError(f"transition limit exceeded ({self.transition_limit})")

            self._step_counts[step.id] = self._step_counts.get(step.id, 0) + 1
            step_names.append(step.name)
            if self.observer is not None:
                self.observer("step.started", workflow, step, None, None)
            result = await self.step_executor.execute(step)
            terminal_outcome = result.outcome
            route = self._select_route(workflow, step, result)
            if self.observer is not None:
                self.observer("step.finished", workflow, step, result, route)

            if route is None:
                step = self._sequential_next(workflow, step)
                continue

            target = route.target
            if target.kind is RouteTargetKind.NEXT_STEP:
                step = self._step_by_id(workflow, target.step_id)
            elif target.kind is RouteTargetKind.JUMP_WORKFLOW:
                workflow, step = self._enter_workflow(
                    self._required_workflow_id(target.workflow_id), workflow_names
                )
            elif target.kind is RouteTargetKind.CALL_WORKFLOW:
                self.task_context.call_stack.append(
                    CallFrame(
                        workflow_id=workflow.id,
                        next_step_id=self._sequential_next_id(workflow, step),
                    )
                )
                workflow, step = self._enter_workflow(
                    self._required_workflow_id(target.workflow_id), workflow_names
                )
            elif target.kind is RouteTargetKind.RETURN:
                if not self.task_context.call_stack:
                    raise RoutingError("cannot return because the call stack is empty")
                frame = self.task_context.call_stack.pop()
                workflow = self._workflow_by_id(frame.workflow_id)
                step = (
                    self._step_by_id(workflow, frame.next_step_id)
                    if frame.next_step_id is not None
                    else None
                )
                if step is not None:
                    workflow_names.append(workflow.name)
            else:
                step = None

        return WorkflowTrace(
            workflow_names=tuple(workflow_names),
            step_names=tuple(step_names),
            terminal_outcome=terminal_outcome,
        )

    def _enter_workflow(
        self,
        workflow_id: UUID,
        trace: list[str],
    ) -> tuple[Workflow, AutomationStep | None]:
        workflow = self._workflow_by_id(workflow_id)
        self._workflow_counts[workflow.id] = self._workflow_counts.get(workflow.id, 0) + 1
        self._workflow_variables.setdefault(workflow.id, {})
        trace.append(workflow.name)
        first_step = workflow.steps[0] if workflow.steps else None
        return workflow, first_step

    def _select_route(
        self,
        workflow: Workflow,
        step: AutomationStep,
        result: StepResult,
    ) -> RouteRule | None:
        for route in step.routes:
            if route.outcome is not result.outcome:
                continue
            if route.predicate is None or self._predicate_matches(route.predicate, workflow):
                return route
        return None

    def _predicate_matches(
        self,
        predicate: RoutePredicate,
        workflow: Workflow,
    ) -> bool:
        if predicate.source == "task_variable":
            values: dict[str, Any] = self.task_context.task_variables
            if predicate.key not in values:
                raise RoutingError(f"missing task variable '{predicate.key}'")
            actual = values[predicate.key]
        elif predicate.source == "workflow_variable":
            values = self._workflow_variables[workflow.id]
            if predicate.key not in values:
                raise RoutingError(
                    f"missing workflow variable '{predicate.key}' in '{workflow.name}'"
                )
            actual = values[predicate.key]
        elif predicate.source == "workflow_count":
            actual = self._workflow_counts.get(UUID(predicate.key), 0)
        else:
            actual = self._step_counts.get(UUID(predicate.key), 0)
        return _compare(actual, predicate.operator, predicate.expected)

    def _workflow_by_id(self, workflow_id: UUID) -> Workflow:
        try:
            return self._workflows[workflow_id]
        except KeyError as error:
            raise RoutingError(f"missing workflow {workflow_id}") from error

    @staticmethod
    def _required_workflow_id(workflow_id: UUID | None) -> UUID:
        if workflow_id is None:
            raise RoutingError("workflow route has no workflow id")
        return workflow_id

    @staticmethod
    def _step_by_id(workflow: Workflow, step_id: UUID | None) -> AutomationStep:
        if step_id is None:
            raise RoutingError("step route has no step id")
        for step in workflow.steps:
            if step.id == step_id:
                return step
        raise RoutingError(f"workflow '{workflow.name}' has no step {step_id}")

    @staticmethod
    def _sequential_next(
        workflow: Workflow,
        current: AutomationStep,
    ) -> AutomationStep | None:
        next_id = WorkflowExecutor._sequential_next_id(workflow, current)
        if next_id is None:
            return None
        return WorkflowExecutor._step_by_id(workflow, next_id)

    @staticmethod
    def _sequential_next_id(workflow: Workflow, current: AutomationStep) -> UUID | None:
        for index, step in enumerate(workflow.steps):
            if step.id == current.id:
                next_index = index + 1
                return workflow.steps[next_index].id if next_index < len(workflow.steps) else None
        raise RoutingError(f"workflow '{workflow.name}' does not contain step {current.id}")


def _compare(actual: Any, operator: ComparisonOperator, expected: Any) -> bool:
    if operator is ComparisonOperator.EQ:
        return bool(actual == expected)
    if operator is ComparisonOperator.NE:
        return bool(actual != expected)
    if operator is ComparisonOperator.LT:
        return bool(actual < expected)
    if operator is ComparisonOperator.LE:
        return bool(actual <= expected)
    if operator is ComparisonOperator.GT:
        return bool(actual > expected)
    return bool(actual >= expected)

from __future__ import annotations

import asyncio
from collections.abc import Callable
from time import monotonic
from uuid import UUID, uuid4

from flow_runner.domain.enums import RunnerState, StepOutcome
from flow_runner.domain.errors import Cancelled, FlowRunnerError
from flow_runner.domain.project import AutomationStep, Project, Workflow
from flow_runner.domain.results import ConditionResult, StepResult
from flow_runner.domain.routing import RouteRule
from flow_runner.engine.cancellation import CancellationToken
from flow_runner.engine.workflow_executor import (
    StepExecutorLike,
    WorkflowExecutor,
    WorkflowTrace,
)
from flow_runner.infrastructure.logging.events import RuntimeEvent
from flow_runner.infrastructure.logging.sinks import EventSink, NullEventSink


class Runner:
    def __init__(
        self,
        step_executor: StepExecutorLike | None = None,
        *,
        step_executor_factory: Callable[[CancellationToken], StepExecutorLike] | None = None,
        event_sink: EventSink | None = None,
    ) -> None:
        if step_executor is None and step_executor_factory is None:
            raise ValueError("runner requires a step executor or factory")
        self.step_executor = step_executor
        self.step_executor_factory = step_executor_factory
        self.event_sink = event_sink or NullEventSink()
        self.state = RunnerState.IDLE
        self.task_id: UUID | None = None
        self.cancellation = CancellationToken()
        self._pause_gate = asyncio.Event()
        self._pause_gate.set()

    async def start(self, project: Project, entry_workflow_id: UUID) -> WorkflowTrace:
        if self.state in {RunnerState.RUNNING, RunnerState.PAUSED}:
            raise FlowRunnerError("runner is already running")

        self.task_id = uuid4()
        self.cancellation = CancellationToken()
        self._pause_gate = asyncio.Event()
        self._pause_gate.set()
        self._set_state(RunnerState.RUNNING, workflow_id=entry_workflow_id)
        delegate = (
            self.step_executor_factory(self.cancellation)
            if self.step_executor_factory is not None
            else self.step_executor
        )
        if delegate is None:
            raise RuntimeError("runner step executor was not configured")
        gated_executor = _GatedStepExecutor(self, delegate)
        workflow_executor = WorkflowExecutor(
            project,
            gated_executor,
            observer=self._observe_transition,
        )

        try:
            trace = await workflow_executor.run(entry_workflow_id)
        except Exception:
            self._set_state(RunnerState.FAILED, workflow_id=entry_workflow_id)
            raise

        if trace.terminal_outcome is StepOutcome.CANCELLED:
            final_state = RunnerState.CANCELLED
        elif trace.terminal_outcome is StepOutcome.FAILURE:
            final_state = RunnerState.FAILED
        else:
            final_state = RunnerState.COMPLETED
        self._set_state(
            final_state,
            workflow_id=entry_workflow_id,
            outcome=trace.terminal_outcome,
        )
        return trace

    def pause(self) -> None:
        if self.state is not RunnerState.RUNNING:
            return
        self._pause_gate.clear()
        self._set_state(RunnerState.PAUSED)

    def resume(self) -> None:
        if self.state is not RunnerState.PAUSED:
            return
        self._pause_gate.set()
        self._set_state(RunnerState.RUNNING)

    def stop(self) -> None:
        if self.state not in {RunnerState.RUNNING, RunnerState.PAUSED}:
            return
        self.cancellation.cancel()
        self._pause_gate.set()

    async def wait_until_active(self) -> None:
        self.cancellation.raise_if_cancelled()
        if self._pause_gate.is_set():
            return
        gate_task = asyncio.create_task(self._pause_gate.wait())
        cancel_task = asyncio.create_task(self.cancellation.wait_cancelled())
        done, pending = await asyncio.wait(
            {gate_task, cancel_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if cancel_task in done:
            self.cancellation.raise_if_cancelled()

    def _set_state(
        self,
        state: RunnerState,
        *,
        workflow_id: UUID | None = None,
        outcome: StepOutcome | None = None,
    ) -> None:
        self.state = state
        if self.task_id is None:
            return
        self.event_sink.emit(
            RuntimeEvent(
                task_id=self.task_id,
                kind="runner.state",
                state=state,
                monotonic_timestamp=monotonic(),
                workflow_id=workflow_id,
                outcome=outcome,
            )
        )

    def _observe_transition(
        self,
        kind: str,
        workflow: Workflow,
        step: AutomationStep,
        result: StepResult | None,
        route: RouteRule | None,
    ) -> None:
        if self.task_id is None:
            return
        details: dict[str, object] = {}
        if result is not None:
            details["result"] = result.model_dump(mode="json")
        if route is not None:
            details["route"] = route.model_dump(mode="json")
        self.event_sink.emit(
            RuntimeEvent(
                task_id=self.task_id,
                kind=kind,
                state=self.state,
                monotonic_timestamp=monotonic(),
                workflow_id=workflow.id,
                step_id=step.id,
                outcome=result.outcome if result is not None else None,
                frame_id=_condition_frame_id(
                    result.condition_result if result is not None else None
                ),
                details=details,
            )
        )


class _GatedStepExecutor:
    def __init__(self, runner: Runner, delegate: StepExecutorLike) -> None:
        self.runner = runner
        self.delegate = delegate

    async def execute(self, step: AutomationStep) -> StepResult:
        try:
            await self.runner.wait_until_active()
            return await self.delegate.execute(step)
        except Cancelled as error:
            return StepResult(outcome=StepOutcome.CANCELLED, error=str(error))


def _condition_frame_id(result: ConditionResult | None) -> str | None:
    if result is None:
        return None
    if result.frame_id is not None:
        return result.frame_id
    for child in result.children.values():
        frame_id = _condition_frame_id(child)
        if frame_id is not None:
            return frame_id
    return None

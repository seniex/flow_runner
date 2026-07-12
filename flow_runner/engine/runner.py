from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import cast
from uuid import UUID, uuid4

from flow_runner.domain.enums import RunnerState, StepOutcome
from flow_runner.domain.errors import Cancelled, FlowRunnerError
from flow_runner.domain.project import AutomationStep, Project, Workflow
from flow_runner.domain.results import ConditionResult, StepResult
from flow_runner.domain.routing import RouteRule
from flow_runner.engine.cancellation import CancellationToken
from flow_runner.engine.context import TaskContext, WorkflowContext
from flow_runner.engine.parallel import ParallelMonitorGroup, ParallelWorkflowTrace
from flow_runner.engine.resources import ResourceEvent
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
        delegate = self._build_step_delegate()
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

    async def start_parallel(
        self,
        project: Project,
        block_id: UUID,
    ) -> ParallelWorkflowTrace:
        if self.state in {RunnerState.RUNNING, RunnerState.PAUSED}:
            raise FlowRunnerError("runner is already running")
        if self.step_executor_factory is None:
            raise FlowRunnerError("parallel execution requires a step executor factory")
        block = next((item for item in project.parallel_blocks if item.id == block_id), None)
        if block is None:
            raise FlowRunnerError(f"missing parallel block {block_id}")

        self.task_id = uuid4()
        self.cancellation = CancellationToken()
        self._pause_gate = asyncio.Event()
        self._pause_gate.set()
        self._set_state(RunnerState.RUNNING)
        group = ParallelMonitorGroup(TaskContext())
        children = []
        for workflow_id in block.workflow_ids:
            child_context = group.child_context()

            async def run_child(
                entry_id: UUID = workflow_id,
                task_context: TaskContext = child_context.task,
            ) -> WorkflowTrace:
                delegate = self._build_step_delegate()
                executor = WorkflowExecutor(
                    project,
                    _GatedStepExecutor(self, delegate),
                    task_context=task_context,
                    observer=self._observe_transition,
                )
                return await executor.run(entry_id)

            children.append(run_child)

        try:
            traces = tuple(await group.run(children))
        except Exception:
            self._set_state(RunnerState.FAILED)
            raise

        outcomes = {trace.terminal_outcome for trace in traces}
        if StepOutcome.CANCELLED in outcomes:
            terminal_outcome = StepOutcome.CANCELLED
            final_state = RunnerState.CANCELLED
        elif StepOutcome.FAILURE in outcomes:
            terminal_outcome = StepOutcome.FAILURE
            final_state = RunnerState.FAILED
        elif StepOutcome.TIMEOUT in outcomes:
            terminal_outcome = StepOutcome.TIMEOUT
            final_state = RunnerState.COMPLETED
        elif StepOutcome.NOT_MATCHED in outcomes:
            terminal_outcome = StepOutcome.NOT_MATCHED
            final_state = RunnerState.COMPLETED
        else:
            terminal_outcome = StepOutcome.SUCCESS
            final_state = RunnerState.COMPLETED
        self._set_state(final_state, outcome=terminal_outcome)
        return ParallelWorkflowTrace(
            block_id=block.id,
            workflow_traces=traces,
            terminal_outcome=terminal_outcome,
        )

    async def run_step(
        self,
        project: Project,
        workflow_id: UUID,
        step_id: UUID,
    ) -> StepResult:
        workflow, step = self._debug_target(project, workflow_id, step_id)
        self._begin_debug_task(workflow_id)
        delegate = self._build_step_delegate()
        self._bind_debug_context(delegate, workflow, step)
        gated = _GatedStepExecutor(self, delegate)
        self._observe_transition("step.started", workflow, step, None, None)
        try:
            result = await gated.execute(step)
        except Exception:
            self._set_state(RunnerState.FAILED, workflow_id=workflow_id)
            raise
        self._observe_transition("step.finished", workflow, step, result, None)
        final_state = (
            RunnerState.CANCELLED
            if result.outcome is StepOutcome.CANCELLED
            else RunnerState.FAILED
            if result.outcome is StepOutcome.FAILURE
            else RunnerState.COMPLETED
        )
        self._set_state(final_state, workflow_id=workflow_id, outcome=result.outcome)
        return result

    async def preview_condition(
        self,
        project: Project,
        workflow_id: UUID,
        step_id: UUID,
    ) -> ConditionResult:
        workflow, step = self._debug_target(project, workflow_id, step_id)
        self._begin_debug_task(workflow_id)
        delegate = self._build_step_delegate()
        self._bind_debug_context(delegate, workflow, step)
        raw_previewer = getattr(delegate, "preview_condition", None)
        if raw_previewer is None:
            self._set_state(RunnerState.FAILED, workflow_id=workflow_id)
            raise FlowRunnerError("step executor does not support condition preview")
        previewer = cast(
            Callable[[AutomationStep], Awaitable[ConditionResult]],
            raw_previewer,
        )
        await self.wait_until_active()
        try:
            result = await previewer(step)
        except Exception:
            self._set_state(RunnerState.FAILED, workflow_id=workflow_id)
            raise
        capture_encoder = getattr(delegate, "diagnostic_capture_base64", None)
        diagnostic_capture = capture_encoder(result) if callable(capture_encoder) else None
        if self.task_id is not None:
            self.event_sink.emit(
                RuntimeEvent(
                    task_id=self.task_id,
                    kind="condition.preview",
                    state=self.state,
                    monotonic_timestamp=monotonic(),
                    workflow_id=workflow.id,
                    step_id=step.id,
                    frame_id=_condition_frame_id(result),
                    diagnostic_capture_base64=diagnostic_capture,
                    details={"condition_result": result.model_dump(mode="json")},
                )
            )
        self._set_state(RunnerState.COMPLETED, workflow_id=workflow_id)
        return result

    def _build_step_delegate(self) -> StepExecutorLike:
        delegate = (
            self.step_executor_factory(self.cancellation)
            if self.step_executor_factory is not None
            else self.step_executor
        )
        if delegate is None:
            raise RuntimeError("runner step executor was not configured")
        return delegate

    def _begin_debug_task(self, workflow_id: UUID) -> None:
        if self.state in {RunnerState.RUNNING, RunnerState.PAUSED}:
            raise FlowRunnerError("runner is already running")
        self.task_id = uuid4()
        self.cancellation = CancellationToken()
        self._pause_gate = asyncio.Event()
        self._pause_gate.set()
        self._set_state(RunnerState.RUNNING, workflow_id=workflow_id)

    @staticmethod
    def _debug_target(
        project: Project,
        workflow_id: UUID,
        step_id: UUID,
    ) -> tuple[Workflow, AutomationStep]:
        errors = project.validate_references()
        if errors:
            raise FlowRunnerError("; ".join(errors))
        for group in project.groups:
            for workflow in group.workflows:
                if workflow.id != workflow_id:
                    continue
                for step in workflow.steps:
                    if step.id == step_id:
                        return workflow, step
                raise FlowRunnerError(f"workflow '{workflow.name}' has no step {step_id}")
        raise FlowRunnerError(f"missing workflow {workflow_id}")

    @staticmethod
    def _bind_debug_context(
        delegate: StepExecutorLike,
        workflow: Workflow,
        step: AutomationStep,
    ) -> None:
        binder = getattr(delegate, "bind_workflow_context", None)
        if binder is None:
            return
        binder(
            WorkflowContext(
                task=TaskContext(),
                workflow_counts={workflow.id: 1},
                step_counts={step.id: 1},
            )
        )

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

    def report_resource_event(self, event: ResourceEvent) -> None:
        if self.task_id is None:
            return
        self.event_sink.emit(
            RuntimeEvent(
                task_id=self.task_id,
                kind=event.kind,
                state=self.state,
                monotonic_timestamp=monotonic(),
                details={
                    "target": event.target,
                    "mode": event.mode,
                    "resources": list(event.resources),
                    "wait_seconds": event.wait_seconds,
                },
            )
        )

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

    def bind_workflow_context(self, context: WorkflowContext) -> None:
        binder = getattr(self.delegate, "bind_workflow_context", None)
        if binder is not None:
            binder(context)

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

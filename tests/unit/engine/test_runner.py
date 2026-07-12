import asyncio
import json

import pytest

from flow_runner.domain.enums import RunnerState, StepOutcome
from flow_runner.domain.errors import FlowRunnerError
from flow_runner.domain.project import AutomationStep, FlowGroup, Project, Workflow
from flow_runner.domain.results import StepResult
from flow_runner.engine.runner import Runner
from flow_runner.infrastructure.logging.sinks import JsonLinesEventSink, MemoryEventSink


def project_with_steps(count=1):
    workflow = Workflow(
        name="main",
        steps=[AutomationStep(name=f"step-{index}") for index in range(count)],
    )
    return Project(name="runner", groups=[FlowGroup(name="g", workflows=[workflow])]), workflow


class ImmediateExecutor:
    async def execute(self, step):
        return StepResult(outcome=StepOutcome.SUCCESS)


class SequencedExecutor:
    def __init__(self):
        self.calls = 0
        self.first_entered = asyncio.Event()
        self.release_first = asyncio.Event()

    async def execute(self, step):
        self.calls += 1
        if self.calls == 1:
            self.first_entered.set()
            await self.release_first.wait()
        return StepResult(outcome=StepOutcome.SUCCESS)


class CancellableExecutor:
    def __init__(self, runner):
        self.runner = runner
        self.entered = asyncio.Event()

    async def execute(self, step):
        self.entered.set()
        await self.runner.cancellation.sleep(60)
        return StepResult(outcome=StepOutcome.SUCCESS)


@pytest.mark.asyncio
async def test_runner_emits_lifecycle_events_and_completes():
    project, workflow = project_with_steps()
    events = MemoryEventSink()
    runner = Runner(ImmediateExecutor(), event_sink=events)

    trace = await runner.start(project, workflow.id)

    assert trace.terminal_outcome is StepOutcome.SUCCESS
    assert runner.state is RunnerState.COMPLETED
    assert [event.kind for event in events.events] == [
        "runner.state",
        "step.started",
        "step.finished",
        "runner.state",
    ]
    assert events.events[2].step_id == workflow.steps[0].id
    assert events.events[2].outcome is StepOutcome.SUCCESS
    assert events.events[2].details["result"]["outcome"] == "success"
    assert all(event.task_id == runner.task_id for event in events.events)
    assert events.events[0].workflow_id == workflow.id


@pytest.mark.asyncio
async def test_runner_pauses_before_starting_the_next_step():
    project, workflow = project_with_steps(count=2)
    executor = SequencedExecutor()
    runner = Runner(executor)
    run_task = asyncio.create_task(runner.start(project, workflow.id))
    await executor.first_entered.wait()

    runner.pause()
    executor.release_first.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert runner.state is RunnerState.PAUSED
    assert executor.calls == 1

    runner.resume()
    await run_task
    assert executor.calls == 2
    assert runner.state is RunnerState.COMPLETED


@pytest.mark.asyncio
async def test_runner_rejects_a_second_start_while_running():
    project, workflow = project_with_steps()
    executor = SequencedExecutor()
    runner = Runner(executor)
    first = asyncio.create_task(runner.start(project, workflow.id))
    await executor.first_entered.wait()

    with pytest.raises(FlowRunnerError, match="already running"):
        await runner.start(project, workflow.id)

    executor.release_first.set()
    await first


@pytest.mark.asyncio
async def test_stop_cancels_a_step_wait_and_finishes_cancelled():
    project, workflow = project_with_steps()
    runner = Runner(ImmediateExecutor())
    executor = CancellableExecutor(runner)
    runner.step_executor = executor
    task = asyncio.create_task(runner.start(project, workflow.id))
    await executor.entered.wait()

    runner.stop()
    trace = await task

    assert trace.terminal_outcome is StepOutcome.CANCELLED
    assert runner.state is RunnerState.CANCELLED


@pytest.mark.asyncio
async def test_json_lines_sink_writes_valid_event_objects(tmp_path):
    project, workflow = project_with_steps()
    path = tmp_path / "events.jsonl"
    runner = Runner(ImmediateExecutor(), event_sink=JsonLinesEventSink(path))

    await runner.start(project, workflow.id)

    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [row["kind"] for row in rows] == [
        "runner.state",
        "step.started",
        "step.finished",
        "runner.state",
    ]
    assert all(row["task_id"] == str(runner.task_id) for row in rows)


@pytest.mark.asyncio
async def test_runner_factory_receives_each_tasks_current_cancellation_token():
    project, workflow = project_with_steps()
    tokens = []

    def factory(token):
        tokens.append(token)
        return ImmediateExecutor()

    runner = Runner(step_executor_factory=factory)
    await runner.start(project, workflow.id)

    assert tokens == [runner.cancellation]


@pytest.mark.asyncio
async def test_runner_can_execute_one_selected_step_without_following_sequence():
    project, workflow = project_with_steps(count=2)
    calls = []

    class Executor:
        async def execute(self, step):
            calls.append(step.id)
            return StepResult(outcome=StepOutcome.SUCCESS)

    runner = Runner(step_executor_factory=lambda token: Executor())

    result = await runner.run_step(project, workflow.id, workflow.steps[1].id)

    assert result.outcome is StepOutcome.SUCCESS
    assert calls == [workflow.steps[1].id]

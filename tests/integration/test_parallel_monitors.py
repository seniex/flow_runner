import asyncio

import pytest

from flow_runner.capabilities.actions.window import WindowAction, WindowActionConfig
from flow_runner.capabilities.registry import CapabilityRegistry
from flow_runner.domain.actions import ActionSpec
from flow_runner.domain.conditions import LeafCondition
from flow_runner.domain.enums import ConditionOutcome, StepOutcome
from flow_runner.domain.project import (
    AutomationStep,
    FlowGroup,
    ParallelBlock,
    Project,
    Workflow,
)
from flow_runner.domain.results import ActionResult, ConditionResult, StepResult
from flow_runner.engine.context import StepContext, TaskContext
from flow_runner.engine.parallel import ParallelMonitorGroup
from flow_runner.engine.runner import Runner
from flow_runner.engine.step_executor import StepExecutor, StepRuntime
from flow_runner.infrastructure.windowing.win32 import Win32WindowController


class FakeWindows:
    def __init__(self):
        self.calls = []

    async def activate(self, title):
        self.calls.append(("activate", title))

    async def minimize(self, title):
        self.calls.append(("minimize", title))

    async def restore(self, title):
        self.calls.append(("restore", title))

    async def move_resize(self, title, geometry):
        self.calls.append(("move_resize", title, geometry))


@pytest.mark.asyncio
async def test_window_action_declares_target_exclusivity_and_calls_adapter():
    windows = FakeWindows()
    action = WindowAction(windows)
    config = WindowActionConfig(operation="move_resize", title="Game", geometry=(1, 2, 800, 600))

    result = await action.execute(config, None)

    assert result.outcome is StepOutcome.SUCCESS
    assert windows.calls == [("move_resize", "Game", (1, 2, 800, 600))]
    assert action.required_resources(config) == frozenset({"window:Game"})


@pytest.mark.asyncio
async def test_win32_window_controller_delegates_to_injected_backend():
    calls = []

    class Backend:
        def activate(self, title):
            calls.append(("activate", title))

        def minimize(self, title):
            calls.append(("minimize", title))

        def restore(self, title):
            calls.append(("restore", title))

        def move_resize(self, title, geometry):
            calls.append(("move_resize", title, geometry))

    controller = Win32WindowController(Backend())
    await controller.activate("Game")
    await controller.move_resize("Game", (1, 2, 3, 4))

    assert calls == [("activate", "Game"), ("move_resize", "Game", (1, 2, 3, 4))]


@pytest.mark.asyncio
async def test_parallel_children_share_task_variables_but_not_workflow_variables():
    task = TaskContext(task_variables={"shared": 1})
    group = ParallelMonitorGroup(task)
    first = group.child_context()
    second = group.child_context()

    first.task.task_variables["shared"] = 2
    first.workflow_variables["local"] = "a"

    assert second.task.task_variables["shared"] == 2
    assert "local" not in second.workflow_variables


@pytest.mark.asyncio
async def test_parallel_group_runs_children_concurrently():
    group = ParallelMonitorGroup(TaskContext())
    entered = 0
    both = asyncio.Event()

    async def child():
        nonlocal entered
        entered += 1
        if entered == 2:
            both.set()
        await both.wait()
        return entered

    results = await group.run([child, child])

    assert results == [2, 2]


@pytest.mark.asyncio
async def test_runner_executes_explicit_parallel_block_concurrently():
    first = Workflow(name="A", steps=[AutomationStep(name="A1")])
    second = Workflow(name="B", steps=[AutomationStep(name="B1")])
    block = ParallelBlock(name="监控", workflow_ids=[first.id, second.id])
    project = Project(
        name="parallel",
        groups=[FlowGroup(name="g", workflows=[first, second])],
        parallel_blocks=[block],
    )
    entered = 0
    both_entered = asyncio.Event()
    release = asyncio.Event()

    class Executor:
        async def execute(self, step):
            nonlocal entered
            entered += 1
            if entered == 2:
                both_entered.set()
            await release.wait()
            return StepResult(outcome=StepOutcome.SUCCESS)

    runner = Runner(step_executor_factory=lambda token: Executor())
    task = asyncio.create_task(runner.start_parallel(project, block.id))
    await asyncio.wait_for(both_entered.wait(), timeout=1)
    release.set()

    trace = await task

    assert [item.step_names for item in trace.workflow_traces] == [("A1",), ("B1",)]
    assert trace.terminal_outcome is StepOutcome.SUCCESS


@pytest.mark.asyncio
async def test_stopping_parallel_block_cancels_all_child_workflows():
    first = Workflow(name="A", steps=[AutomationStep(name="A1")])
    second = Workflow(name="B", steps=[AutomationStep(name="B1")])
    block = ParallelBlock(name="监控", workflow_ids=[first.id, second.id])
    project = Project(
        name="parallel",
        groups=[FlowGroup(name="g", workflows=[first, second])],
        parallel_blocks=[block],
    )
    entered = 0
    both_entered = asyncio.Event()

    class Executor:
        def __init__(self, token):
            self.token = token

        async def execute(self, step):
            nonlocal entered
            entered += 1
            if entered == 2:
                both_entered.set()
            await self.token.sleep(60)
            return StepResult(outcome=StepOutcome.SUCCESS)

    runner = Runner(step_executor_factory=lambda token: Executor(token))
    task = asyncio.create_task(runner.start_parallel(project, block.id))
    await asyncio.wait_for(both_entered.wait(), timeout=1)

    runner.stop()
    trace = await task

    assert trace.terminal_outcome is StepOutcome.CANCELLED
    assert all(item.terminal_outcome is StepOutcome.CANCELLED for item in trace.workflow_traces)


@pytest.mark.asyncio
async def test_runner_parallel_children_share_task_variables_through_step_executor():
    shared_written = asyncio.Event()

    class WriteShared:
        name = "test.write_shared"
        config_model = WindowActionConfig

        async def execute(self, config, context):
            context.task_variables["ready"] = True
            shared_written.set()
            return ActionResult(outcome=StepOutcome.SUCCESS)

        def required_resources(self, config):
            return frozenset()

    class ReadShared:
        name = "test.read_shared"
        config_model = WindowActionConfig

        async def evaluate(self, config, context):
            await shared_written.wait()
            outcome = (
                ConditionOutcome.MATCH
                if context.task_variables.get("ready") is True
                else ConditionOutcome.NO_MATCH
            )
            return ConditionResult(node_id="shared", outcome=outcome)

        def required_resources(self, config):
            return frozenset()

    registry = CapabilityRegistry()
    registry.register_action(WriteShared())
    registry.register_condition(ReadShared())
    writer = Workflow(
        name="writer",
        steps=[
            AutomationStep(
                name="write",
                actions=[
                    ActionSpec(
                        capability="test.write_shared",
                        config={"operation": "activate", "title": "unused"},
                    )
                ],
            )
        ],
    )
    reader = Workflow(
        name="reader",
        steps=[
            AutomationStep(
                name="read",
                condition=LeafCondition(
                    id="shared",
                    capability="test.read_shared",
                    config={"operation": "activate", "title": "unused"},
                ),
            )
        ],
    )
    block = ParallelBlock(name="shared", workflow_ids=[writer.id, reader.id])
    project = Project(
        name="parallel",
        groups=[FlowGroup(name="g", workflows=[writer, reader])],
        parallel_blocks=[block],
    )

    def executor_factory(token):
        return StepExecutor(
            StepRuntime(
                registry=registry,
                context=StepContext(),
                cancellation=token,
            )
        )

    trace = await Runner(step_executor_factory=executor_factory).start_parallel(
        project,
        block.id,
    )

    assert trace.terminal_outcome is StepOutcome.SUCCESS
    assert all(item.terminal_outcome is StepOutcome.SUCCESS for item in trace.workflow_traces)

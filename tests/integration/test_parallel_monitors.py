import asyncio

import pytest

from flow_runner.capabilities.actions.window import WindowAction, WindowActionConfig
from flow_runner.domain.enums import StepOutcome
from flow_runner.engine.context import TaskContext
from flow_runner.engine.parallel import ParallelMonitorGroup


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

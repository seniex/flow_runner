import asyncio
from collections import deque

import pytest
from pydantic import BaseModel

from flow_runner.capabilities.registry import CapabilityRegistry
from flow_runner.domain.enums import ConditionMode, ConditionOutcome, StepOutcome
from flow_runner.domain.project import AutomationStep
from flow_runner.domain.results import ActionResult, ConditionResult
from flow_runner.engine.cancellation import CancellationToken
from flow_runner.engine.context import StepContext
from flow_runner.engine.perception import PerceptionService
from flow_runner.engine.resources import ResourceCoordinator
from flow_runner.engine.step_executor import StepExecutor, StepRuntime


class EmptyConfig(BaseModel):
    pass


class QueuedCondition:
    name = "fake.condition"
    config_model = EmptyConfig

    def __init__(self, results):
        self.results = deque(results)
        self.call_count = 0

    async def evaluate(self, config, context):
        self.call_count += 1
        return self.results.popleft()

    def required_resources(self, config):
        return frozenset()


class CountingAction:
    config_model = EmptyConfig

    def __init__(self, name, outcomes=None):
        self.name = name
        self.outcomes = deque(outcomes or [StepOutcome.SUCCESS])
        self.call_count = 0

    async def execute(self, config, context):
        self.call_count += 1
        outcome = self.outcomes.popleft() if self.outcomes else StepOutcome.SUCCESS
        return ActionResult(outcome=outcome)

    def required_resources(self, config):
        return frozenset()


def build_runtime(condition, *actions):
    registry = CapabilityRegistry()
    registry.register_condition(condition)
    for action in actions:
        registry.register_action(action)
    delays = []

    async def fake_sleep(seconds):
        delays.append(seconds)

    runtime = StepRuntime(
        registry=registry,
        context=StepContext(),
        cancellation=CancellationToken(),
        sleep=fake_sleep,
    )
    return runtime, delays


@pytest.mark.asyncio
async def test_once_no_match_returns_not_matched_without_retry():
    condition = QueuedCondition(
        [ConditionResult(node_id="provider", outcome=ConditionOutcome.NO_MATCH)]
    )
    runtime, delays = build_runtime(condition)
    step = AutomationStep(
        name="once",
        condition={"id": "ocr", "capability": condition.name, "config": {}},
    )

    result = await StepExecutor(runtime).execute(step)

    assert result.outcome is StepOutcome.NOT_MATCHED
    assert result.condition_result.node_id == "ocr"
    assert condition.call_count == 1
    assert delays == []
    assert runtime.context.result is None


@pytest.mark.asyncio
async def test_shared_resource_coordinator_serializes_exclusive_actions():
    active = 0
    maximum_active = 0

    class ExclusiveAction(CountingAction):
        async def execute(self, config, context):
            nonlocal active, maximum_active
            active += 1
            maximum_active = max(maximum_active, active)
            await asyncio.sleep(0.02)
            active -= 1
            return ActionResult(outcome=StepOutcome.SUCCESS)

        def required_resources(self, config):
            return frozenset({"mouse"})

    action = ExclusiveAction("exclusive")
    registry = CapabilityRegistry()
    registry.register_action(action)
    coordinator = ResourceCoordinator()
    step = AutomationStep(
        name="exclusive",
        actions=[{"capability": "exclusive", "config": {}}],
    )

    def executor():
        return StepExecutor(
            StepRuntime(
                registry=registry,
                context=StepContext(),
                cancellation=CancellationToken(),
                resources=coordinator,
            )
        )

    await asyncio.gather(executor().execute(step), executor().execute(step))

    assert maximum_active == 1


@pytest.mark.asyncio
async def test_stale_visual_result_is_revalidated_before_bound_mouse_action():
    class Capture:
        async def capture(self, target):
            raise AssertionError("capture is not needed by this fake condition")

    perception = PerceptionService(Capture())
    coordinator = ResourceCoordinator(perception)

    class VisualCondition:
        name = "visual"
        config_model = EmptyConfig

        def __init__(self):
            self.calls = 0

        async def evaluate(self, config, context):
            self.calls += 1
            generation = perception.current_generation("desktop")
            result = ConditionResult(
                node_id=self.name,
                outcome=ConditionOutcome.MATCH,
                position=(10, 10) if self.calls == 1 else (20, 30),
                target="desktop",
                frame_id=f"frame-{self.calls}",
                scene_generation=generation,
            )
            if self.calls == 1:
                perception.mark_scene_changed("desktop")
            return result

        def required_resources(self, config):
            return frozenset({"observe:desktop"})

    class PositionConfig(BaseModel):
        position: tuple[int, int]

    class MouseAction:
        name = "mouse"
        config_model = PositionConfig

        def __init__(self):
            self.positions = []

        async def execute(self, config, context):
            self.positions.append(config.position)
            return ActionResult(outcome=StepOutcome.SUCCESS)

        def required_resources(self, config):
            return frozenset({"mouse"})

    condition = VisualCondition()
    action = MouseAction()
    registry = CapabilityRegistry()
    registry.register_condition(condition)
    registry.register_action(action)
    step = AutomationStep.model_validate(
        {
            "name": "fresh click",
            "condition": {"id": "screen", "capability": "visual", "config": {}},
            "actions": [
                {
                    "capability": "mouse",
                    "config": {"position": "$result.primary.position"},
                }
            ],
        }
    )
    runtime = StepRuntime(
        registry=registry,
        context=StepContext(),
        cancellation=CancellationToken(),
        resources=coordinator,
    )

    result = await StepExecutor(runtime).execute(step)

    assert result.outcome is StepOutcome.SUCCESS
    assert result.condition_result is not None
    assert result.condition_result.position == (20, 30)
    assert condition.calls == 2
    assert action.positions == [(20, 30)]


@pytest.mark.asyncio
async def test_condition_preview_does_not_execute_main_actions():
    condition = QueuedCondition(
        [ConditionResult(node_id="provider", outcome=ConditionOutcome.MATCH, text="ready")]
    )
    action = CountingAction("action")
    runtime, _ = build_runtime(condition, action)
    step = AutomationStep.model_validate(
        {
            "name": "preview",
            "condition": {"id": "screen", "capability": condition.name, "config": {}},
            "actions": [{"capability": action.name, "config": {}}],
        }
    )

    result = await StepExecutor(runtime).preview_condition(step)

    assert result.outcome is ConditionOutcome.MATCH
    assert result.text == "ready"
    assert action.call_count == 0


@pytest.mark.asyncio
async def test_until_runs_after_no_match_hook_and_times_out():
    condition = QueuedCondition(
        [
            ConditionResult(node_id="provider", outcome=ConditionOutcome.NO_MATCH),
            ConditionResult(node_id="provider", outcome=ConditionOutcome.NO_MATCH),
            ConditionResult(node_id="provider", outcome=ConditionOutcome.NO_MATCH),
        ]
    )
    recover = CountingAction("fake.recover")
    runtime, delays = build_runtime(condition, recover)
    step = AutomationStep.model_validate(
        {
            "name": "wait",
            "condition": {"id": "ocr", "capability": condition.name, "config": {}},
            "condition_policy": {
                "mode": ConditionMode.UNTIL,
                "max_attempts": 3,
                "interval_seconds": 0.25,
                "after_no_match_actions": [{"capability": recover.name, "config": {}}],
            },
        }
    )

    result = await StepExecutor(runtime).execute(step)

    assert result.outcome is StepOutcome.TIMEOUT
    assert condition.call_count == 3
    assert recover.call_count == 3
    assert delays == [0.25, 0.25]


@pytest.mark.asyncio
async def test_match_runs_main_actions_only_after_condition():
    condition = QueuedCondition(
        [ConditionResult(node_id="provider", outcome=ConditionOutcome.MATCH)]
    )
    main_action = CountingAction("fake.main")
    runtime, _ = build_runtime(condition, main_action)
    step = AutomationStep.model_validate(
        {
            "name": "match",
            "condition": {"id": "image", "capability": condition.name, "config": {}},
            "actions": [{"capability": main_action.name, "config": {}}],
        }
    )

    result = await StepExecutor(runtime).execute(step)

    assert result.outcome is StepOutcome.SUCCESS
    assert main_action.call_count == 1


@pytest.mark.asyncio
async def test_action_failure_retries_then_returns_failure():
    condition = QueuedCondition(
        [ConditionResult(node_id="provider", outcome=ConditionOutcome.MATCH)]
    )
    action = CountingAction(
        "fake.flaky",
        outcomes=[StepOutcome.FAILURE, StepOutcome.FAILURE],
    )
    runtime, delays = build_runtime(condition, action)
    step = AutomationStep.model_validate(
        {
            "name": "flaky",
            "condition": {"id": "image", "capability": condition.name, "config": {}},
            "actions": [{"capability": action.name, "config": {}}],
            "action_policy": {"max_attempts": 2, "retry_interval_seconds": 0.1},
        }
    )

    result = await StepExecutor(runtime).execute(step)

    assert result.outcome is StepOutcome.FAILURE
    assert action.call_count == 2
    assert delays == [0.1]


@pytest.mark.asyncio
async def test_cancelled_step_returns_cancelled_without_another_attempt():
    condition = QueuedCondition(
        [ConditionResult(node_id="provider", outcome=ConditionOutcome.NO_MATCH)]
    )
    runtime, _ = build_runtime(condition)

    async def cancel_during_sleep(seconds):
        runtime.cancellation.cancel()
        await runtime.cancellation.sleep(seconds)

    runtime.sleep = cancel_during_sleep
    step = AutomationStep.model_validate(
        {
            "name": "cancel",
            "condition": {"id": "ocr", "capability": condition.name, "config": {}},
            "condition_policy": {
                "mode": ConditionMode.UNTIL,
                "max_attempts": 2,
                "interval_seconds": 1,
            },
        }
    )

    result = await StepExecutor(runtime).execute(step)

    assert result.outcome is StepOutcome.CANCELLED
    assert condition.call_count == 1

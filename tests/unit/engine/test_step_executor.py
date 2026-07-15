import asyncio
import base64
from collections import deque
from contextlib import asynccontextmanager
from io import BytesIO

import pytest
from PIL import Image
from pydantic import BaseModel

from flow_runner.capabilities.actions.mouse import MouseAction
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
async def test_global_action_defaults_to_desktop_unless_provider_binds_to_scene():
    targets = []

    class RecordingCoordinator(ResourceCoordinator):
        @asynccontextmanager
        async def interact(self, target, *, resources=()):
            targets.append(target)
            yield

    class VisualCondition(QueuedCondition):
        pass

    class GlobalAction(CountingAction):
        def required_resources(self, config):
            return frozenset({"keyboard"})

    class SceneAction(CountingAction):
        binds_to_scene = True

        def required_resources(self, config):
            return frozenset({"mouse"})

    condition = VisualCondition(
        [
            ConditionResult(
                node_id="visual",
                outcome=ConditionOutcome.MATCH,
                target="window:game",
                frame_id="frame",
                scene_generation=0,
            ),
            ConditionResult(
                node_id="visual",
                outcome=ConditionOutcome.MATCH,
                target="window:game",
                frame_id="frame",
                scene_generation=0,
            ),
        ]
    )
    global_action = GlobalAction("global")
    scene_action = SceneAction("scene")
    registry = CapabilityRegistry()
    registry.register_condition(condition)
    registry.register_action(global_action)
    registry.register_action(scene_action)
    executor = StepExecutor(
        StepRuntime(
            registry=registry,
            context=StepContext(),
            cancellation=CancellationToken(),
            resources=RecordingCoordinator(),
        )
    )

    for capability in (global_action.name, scene_action.name):
        step = AutomationStep(
            name=capability,
            condition={"id": "visual", "capability": condition.name, "config": {}},
            actions=[{"capability": capability, "config": {}}],
        )
        result = await executor.execute(step)
        assert result.outcome is StepOutcome.SUCCESS

    assert targets == ["desktop", "window:game"]


@pytest.mark.asyncio
async def test_cancellation_interrupts_waiting_for_exclusive_resource():
    events = []
    coordinator = ResourceCoordinator(event_sink=events.append)
    holder_entered = asyncio.Event()
    release_holder = asyncio.Event()

    async def holder():
        async with coordinator.interact("desktop", resources={"mouse"}):
            holder_entered.set()
            await release_holder.wait()

    class ExclusiveAction(CountingAction):
        def required_resources(self, config):
            return frozenset({"mouse"})

    action = ExclusiveAction("exclusive")
    registry = CapabilityRegistry()
    registry.register_action(action)
    token = CancellationToken()
    executor = StepExecutor(
        StepRuntime(
            registry=registry,
            context=StepContext(),
            cancellation=token,
            resources=coordinator,
        )
    )
    step = AutomationStep(
        name="waiting",
        actions=[{"capability": "exclusive", "config": {}}],
    )
    holder_task = asyncio.create_task(holder())
    await holder_entered.wait()
    step_task = asyncio.create_task(executor.execute(step))
    await asyncio.wait_for(
        _wait_until(lambda: any(event.kind == "resource.wait.started" for event in events)),
        timeout=1,
    )

    token.cancel()
    try:
        result = await asyncio.wait_for(step_task, timeout=0.2)
    finally:
        release_holder.set()
        await holder_task

    assert result.outcome is StepOutcome.CANCELLED


@pytest.mark.asyncio
async def test_cancellation_interrupts_an_action_that_is_already_running():
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    class BlockingAction(CountingAction):
        async def execute(self, config, context):
            del config, context
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

    action = BlockingAction("blocking")
    registry = CapabilityRegistry()
    registry.register_action(action)
    token = CancellationToken()
    executor = StepExecutor(
        StepRuntime(
            registry=registry,
            context=StepContext(),
            cancellation=token,
        )
    )
    step = AutomationStep(
        name="blocking",
        actions=[{"capability": action.name, "config": {}}],
    )
    task = asyncio.create_task(executor.execute(step))
    await entered.wait()

    token.cancel()
    result = await asyncio.wait_for(task, timeout=0.2)

    assert result.outcome is StepOutcome.CANCELLED
    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_cancellation_interrupts_waiting_for_observation_resource():
    events = []
    coordinator = ResourceCoordinator(event_sink=events.append)
    holder_entered = asyncio.Event()
    release_holder = asyncio.Event()

    async def holder():
        async with coordinator.interact("desktop"):
            holder_entered.set()
            await release_holder.wait()

    class ObservedCondition(QueuedCondition):
        def required_resources(self, config):
            return frozenset({"observe:desktop"})

    condition = ObservedCondition(
        [ConditionResult(node_id="observed", outcome=ConditionOutcome.MATCH)]
    )
    registry = CapabilityRegistry()
    registry.register_condition(condition)
    token = CancellationToken()
    executor = StepExecutor(
        StepRuntime(
            registry=registry,
            context=StepContext(),
            cancellation=token,
            resources=coordinator,
        )
    )
    step = AutomationStep(
        name="observing",
        condition={"id": "observed", "capability": condition.name, "config": {}},
    )
    holder_task = asyncio.create_task(holder())
    await holder_entered.wait()
    step_task = asyncio.create_task(executor.execute(step))
    await asyncio.wait_for(
        _wait_until(lambda: any(event.kind == "resource.wait.started" for event in events)),
        timeout=1,
    )

    token.cancel()
    try:
        result = await asyncio.wait_for(step_task, timeout=0.2)
    finally:
        release_holder.set()
        await holder_task

    assert result.outcome is StepOutcome.CANCELLED


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
async def test_dynamic_mouse_position_is_always_executed_in_screen_space():
    condition = QueuedCondition(
        [
            ConditionResult(
                node_id="provider",
                outcome=ConditionOutcome.MATCH,
                position=(325, 240),
            )
        ]
    )

    class MouseDevice:
        def __init__(self):
            self.positions = []

        async def click(self, **kwargs):
            self.positions.append(kwargs["position"])

    async def unexpected_window_origin(target):
        pytest.fail(f"dynamic position was offset for {target}")

    device = MouseDevice()
    action = MouseAction(device, window_origin=unexpected_window_origin)
    runtime, _delays = build_runtime(condition, action)
    step = AutomationStep.model_validate(
        {
            "name": "absolute result click",
            "condition": {"id": "screen", "capability": condition.name, "config": {}},
            "actions": [
                {
                    "capability": "input.mouse",
                    "config": {
                        "operation": "click",
                        "position": "$result.primary.position",
                        "target": "window:Game",
                        "coordinate_space": "target",
                    },
                }
            ],
        }
    )

    result = await StepExecutor(runtime).execute(step)

    assert result.outcome is StepOutcome.SUCCESS
    assert device.positions == [(325, 240)]


@pytest.mark.asyncio
async def test_fixed_mouse_actions_do_not_revalidate_condition_after_scene_changes():
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
            return ConditionResult(
                node_id=self.name,
                outcome=ConditionOutcome.MATCH,
                target="desktop",
                frame_id="frame-1",
                scene_generation=perception.current_generation("desktop"),
            )

        def required_resources(self, config):
            return frozenset({"observe:desktop"})

    class PositionConfig(BaseModel):
        position: tuple[int, int]

    class MouseAction:
        name = "mouse"
        config_model = PositionConfig
        binds_to_scene = True

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
            "name": "fixed clicks",
            "condition": {"id": "screen", "capability": "visual", "config": {}},
            "actions": [
                {"capability": "mouse", "config": {"position": [10, 20]}},
                {"capability": "mouse", "config": {"position": [30, 40]}},
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
    assert condition.calls == 1
    assert action.positions == [(10, 20), (30, 40)]


@pytest.mark.asyncio
async def test_composite_visual_conditions_share_one_frame_per_evaluation_tick():
    class Capture:
        def __init__(self):
            self.calls = 0

        async def capture(self, target):
            self.calls += 1
            return Image.new("RGB", (10, 10), "white")

    capture = Capture()
    perception = PerceptionService(capture)

    class VisualCondition:
        name = "visual"
        config_model = EmptyConfig

        async def evaluate(self, config, context):
            snapshot = await perception.snapshot("desktop")
            return ConditionResult(
                node_id=self.name,
                outcome=ConditionOutcome.MATCH,
                target="desktop",
                frame_id=snapshot.frame_id,
                scene_generation=snapshot.scene_generation,
            )

        def required_resources(self, config):
            return frozenset({"observe:desktop"})

    registry = CapabilityRegistry()
    registry.register_condition(VisualCondition())
    executor = StepExecutor(
        StepRuntime(
            registry=registry,
            context=StepContext(),
            cancellation=CancellationToken(),
            resources=ResourceCoordinator(perception),
        )
    )
    step = AutomationStep.model_validate(
        {
            "name": "shared frame",
            "condition": {
                "id": "all",
                "operator": "and",
                "children": [
                    {"id": "first", "capability": "visual", "config": {}},
                    {"id": "second", "capability": "visual", "config": {}},
                ],
            },
        }
    )

    first_result = await executor.execute(step)
    second_result = await executor.execute(step)

    assert capture.calls == 2
    assert first_result.condition_result is not None
    assert second_result.condition_result is not None
    first_children = first_result.condition_result.children
    second_children = second_result.condition_result.children
    assert first_children["first"].frame_id == first_children["second"].frame_id
    assert second_children["first"].frame_id == second_children["second"].frame_id
    assert first_children["first"].frame_id != second_children["first"].frame_id


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
async def test_visual_preview_can_encode_its_perception_frame_without_disk_io():
    class Capture:
        async def capture(self, target):
            return Image.new("RGB", (5, 4), "white")

    perception = PerceptionService(Capture())
    snapshot = await perception.snapshot("desktop")
    runtime = StepRuntime(
        registry=CapabilityRegistry(),
        context=StepContext(),
        cancellation=CancellationToken(),
        resources=ResourceCoordinator(perception),
    )
    result = ConditionResult(
        node_id="visual",
        outcome=ConditionOutcome.MATCH,
        target="desktop",
        frame_id=snapshot.frame_id,
        scene_generation=snapshot.scene_generation,
    )

    encoded = StepExecutor(runtime).diagnostic_capture_base64(result)

    assert encoded is not None
    image = Image.open(BytesIO(base64.b64decode(encoded)))
    assert image.size == (5, 4)


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
    assert result.condition_attempts == 3
    assert condition.call_count == 3
    assert recover.call_count == 3
    assert delays == [0.25, 0.25]


@pytest.mark.asyncio
async def test_action_binding_error_uses_retry_policy_and_returns_failure():
    class PositionConfig(BaseModel):
        position: tuple[int, int]

    class BoundAction(CountingAction):
        config_model = PositionConfig

    action = BoundAction("bound")
    registry = CapabilityRegistry()
    registry.register_action(action)
    delays = []

    async def sleep(seconds):
        delays.append(seconds)

    runtime = StepRuntime(
        registry=registry,
        context=StepContext(),
        cancellation=CancellationToken(),
        sleep=sleep,
    )
    step = AutomationStep.model_validate(
        {
            "name": "bad binding",
            "actions": [
                {
                    "capability": "bound",
                    "config": {"position": "$result.primary.position"},
                }
            ],
            "action_policy": {"max_attempts": 2, "retry_interval_seconds": 0.1},
        }
    )

    result = await StepExecutor(runtime).execute(step)

    assert result.outcome is StepOutcome.FAILURE
    assert len(result.action_results) == 1
    assert result.action_results[0].attempts == 2
    assert "condition result" in (result.action_results[0].error or "")
    assert action.call_count == 0
    assert delays == [0.1]


@pytest.mark.asyncio
async def test_invalid_condition_config_becomes_structured_failure():
    class RequiredConfig(BaseModel):
        value: int

    class RequiredCondition(QueuedCondition):
        config_model = RequiredConfig

    condition = RequiredCondition([])
    registry = CapabilityRegistry()
    registry.register_condition(condition)
    runtime = StepRuntime(
        registry=registry,
        context=StepContext(),
        cancellation=CancellationToken(),
    )
    step = AutomationStep(
        name="invalid condition",
        condition={"id": "required", "capability": condition.name, "config": {}},
    )

    result = await StepExecutor(runtime).execute(step)

    assert result.outcome is StepOutcome.FAILURE
    assert result.condition_result is not None
    assert "value" in str(result.condition_result.provider_data["error"])
    assert condition.call_count == 0


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
    assert result.condition_attempts == 1
    assert result.condition_result is not None
    assert result.condition_result.outcome is ConditionOutcome.NO_MATCH
    assert condition.call_count == 1


@pytest.mark.asyncio
async def test_cancelled_before_first_condition_evaluation_reports_zero_attempts():
    condition = QueuedCondition(
        [ConditionResult(node_id="provider", outcome=ConditionOutcome.NO_MATCH)]
    )
    runtime, _ = build_runtime(condition)
    runtime.cancellation.cancel()
    step = AutomationStep(
        name="cancel before evaluation",
        condition={"id": "ocr", "capability": condition.name, "config": {}},
    )

    result = await StepExecutor(runtime).execute(step)

    assert result.outcome is StepOutcome.CANCELLED
    assert result.condition_attempts == 0
    assert result.condition_result is None
    assert condition.call_count == 0


async def _wait_until(predicate):
    while not predicate():
        await asyncio.sleep(0)

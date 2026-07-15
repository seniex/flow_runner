# Runtime Control and Icon System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add strict cooperative pause/stop behavior, an optional minimize-on-workflow-start setting, and a high-contrast application/command/tree icon system.

**Architecture:** Extend the per-run `CancellationToken` into the single lifecycle gate used by the runner, conditions, waits, input timing, and playback. Keep the standalone recorder owned by `ApplicationComposition`, but synchronize it through accepted lifecycle signals from the existing Qt bridge and main window. Store minimization in project settings, and load all SVG assets through one UI icon helper plus the central stylesheet.

**Tech Stack:** Python 3.11+, asyncio, PySide6, QSS/SVG resources, pytest, pytest-asyncio, pytest-qt, Ruff, mypy.

---

## Execution Setup

- Implement from commit `d8fd2d5` or its descendant.
- Invoke `superpowers:using-git-worktrees` before editing and create an isolated feature worktree.
- Do not copy, stage, or modify the main worktree's `data/project.json` user changes.
- Use global Python for every command in this plan.
- Apply TDD: run each new test first and confirm the specified failure before implementation.

## File Map

**Engine lifecycle**

- Modify `flow_runner/engine/cancellation.py`: cancellation, pause state, active clock, and pause-aware sleep.
- Modify `flow_runner/engine/runner.py`: delegate all pause state to the lifecycle token.
- Modify `flow_runner/engine/step_executor.py`: cancel in-flight condition providers and preserve lifecycle checks.
- Create `tests/unit/engine/test_cancellation.py`.
- Modify `tests/unit/engine/test_runner.py` and `tests/unit/engine/test_step_executor.py`.

**Input and recording**

- Modify `flow_runner/infrastructure/input/mouse.py` and `keyboard.py`: bind per-run timing callbacks.
- Modify `flow_runner/capabilities/actions/mouse.py`: inject lifecycle sleep for settle delay.
- Modify `flow_runner/infrastructure/input/recording.py`: pause/resume independent recording with active timestamps.
- Modify `flow_runner/app.py`: bind input timing and coordinate recorder lifecycle.
- Modify `tests/integration/test_actions.py` and `tests/ui/test_app_smoke.py`.

**Qt control and settings**

- Modify `flow_runner/ui/runner_bridge.py`: return acceptance from start/pause/resume/stop requests.
- Modify `flow_runner/ui/main_window.py`: lifecycle acceptance signals and post-acceptance minimization.
- Modify `flow_runner/ui/dialogs/settings_dialog.py`: project setting checkbox.
- Modify `tests/ui/test_runner_bridge.py` and `tests/ui/test_main_window.py`.

**Icons and Windows identity**

- Create `flow_runner/ui/icons.py`: resource lookup and action-icon application.
- Create `flow_runner/infrastructure/windowing/identity.py`: Windows application user model ID.
- Create SVG files under `flow_runner/resources/icons/` listed in Task 7.
- Modify `flow_runner/ui/theme_manager.py`, `flow_runner/ui/widgets/responsive_controls.py`, `flow_runner/resources/styles/base.qss`, `flow_runner/app.py`, and `flow_runner/ui/main_window.py`.
- Create `tests/unit/infrastructure/test_window_identity.py` and `tests/ui/test_icons.py`.
- Modify `tests/ui/test_theme_manager.py` and `tests/unit/test_package.py`.

**Documentation**

- Modify `README.md`: setting, lifecycle semantics, and icon behavior.

---

### Task 1: Shared Cancellation and Pause Lifecycle

**Files:**

- Create: `tests/unit/engine/test_cancellation.py`
- Modify: `tests/unit/engine/test_runner.py`
- Modify: `flow_runner/engine/cancellation.py`
- Modify: `flow_runner/engine/runner.py`
- Modify: `flow_runner/engine/step_executor.py`

- [ ] **Step 1: Write failing lifecycle-token tests**

Create tests that prove pause blocks checkpoints, cancellation wakes paused waiters, and active time excludes a paused interval:

```python
import asyncio

import pytest

from flow_runner.domain.errors import Cancelled
from flow_runner.engine.cancellation import CancellationToken


@pytest.mark.asyncio
async def test_pause_blocks_checkpoint_until_resume():
    token = CancellationToken()
    token.pause()
    waiter = asyncio.create_task(token.wait_until_active())
    await asyncio.sleep(0)
    assert not waiter.done()
    token.resume()
    await asyncio.wait_for(waiter, timeout=0.2)


@pytest.mark.asyncio
async def test_cancel_wakes_a_paused_checkpoint():
    token = CancellationToken()
    token.pause()
    waiter = asyncio.create_task(token.wait_until_active())
    await asyncio.sleep(0)
    token.cancel()
    with pytest.raises(Cancelled, match="execution cancelled"):
        await asyncio.wait_for(waiter, timeout=0.2)


def test_active_time_excludes_paused_duration():
    now = 10.0
    token = CancellationToken(clock=lambda: now)
    now = 12.0
    token.pause()
    now = 17.0
    assert token.active_time() == pytest.approx(12.0)
    token.resume()
    now = 20.0
    assert token.active_time() == pytest.approx(15.0)
```

Also add a runner regression test:

```python
@pytest.mark.asyncio
async def test_stop_cancels_while_runner_is_paused():
    project, workflow = project_with_steps()
    runner = Runner(ImmediateExecutor())
    executor = CancellableExecutor(runner)
    runner.step_executor = executor
    task = asyncio.create_task(runner.start(project, workflow.id))
    await executor.entered.wait()
    runner.pause()
    runner.stop()
    trace = await asyncio.wait_for(task, timeout=0.2)
    assert trace.terminal_outcome is StepOutcome.CANCELLED
```

- [ ] **Step 2: Run tests and verify the expected failure**

Run:

```powershell
python -m pytest tests/unit/engine/test_cancellation.py tests/unit/engine/test_runner.py::test_stop_cancels_while_runner_is_paused -q
```

Expected: FAIL because `CancellationToken` has no `pause`, `resume`, `wait_until_active`, or `active_time` behavior.

- [ ] **Step 3: Implement the shared lifecycle token**

Update `CancellationToken` to own `_cancelled`, `_active`, `_paused`, `_paused_at`, and `_paused_total`. Use `time.monotonic` as the injectable default clock. Its public behavior must match this interface:

```python
class CancellationToken:
    def __init__(self, *, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._cancelled = asyncio.Event()
        self._active = asyncio.Event()
        self._active.set()
        self._paused = asyncio.Event()
        self._paused_at: float | None = None
        self._paused_total = 0.0

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()

    def cancel(self) -> None:
        self._cancelled.set()
        self._active.set()

    def pause(self) -> None:
        if self.is_cancelled or self.is_paused:
            return
        self._paused_at = self._clock()
        self._paused.set()
        self._active.clear()

    def resume(self) -> None:
        if not self.is_paused:
            return
        assert self._paused_at is not None
        self._paused_total += max(0.0, self._clock() - self._paused_at)
        self._paused_at = None
        self._paused.clear()
        self._active.set()

    def active_time(self) -> float:
        paused_now = (
            max(0.0, self._clock() - self._paused_at)
            if self._paused_at is not None
            else 0.0
        )
        return self._clock() - self._paused_total - paused_now

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise Cancelled("execution cancelled")

    async def wait_cancelled(self) -> None:
        await self._cancelled.wait()

    async def wait_until_active(self) -> None:
        self.raise_if_cancelled()
        if self._active.is_set():
            return
        active_task = asyncio.create_task(self._active.wait())
        cancel_task = asyncio.create_task(self._cancelled.wait())
        done, pending = await asyncio.wait(
            {active_task, cancel_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if cancel_task in done:
            self.raise_if_cancelled()

    async def sleep(self, seconds: float) -> None:
        remaining = max(0.0, seconds)
        while True:
            await self.wait_until_active()
            if remaining <= 0:
                await asyncio.sleep(0)
                self.raise_if_cancelled()
                return
            started = self._clock()
            timer = asyncio.create_task(asyncio.sleep(remaining))
            paused = asyncio.create_task(self._paused.wait())
            cancelled = asyncio.create_task(self._cancelled.wait())
            done, pending = await asyncio.wait(
                {timer, paused, cancelled}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            if cancelled in done:
                self.raise_if_cancelled()
            if timer in done:
                return
            remaining = max(0.0, remaining - (self._clock() - started))
```

In `Runner`, remove the private `_pause_gate`; delegate `pause`, `resume`, and `wait_until_active` to the current token. `stop` calls `cancel()` directly; cancellation already wakes paused waiters. In `StepRuntime`, change `clock` to `ClockCallable | None = None`, add `now()` returning `(self.clock or self.cancellation.active_time)()`, and replace both direct `runtime.clock()` calls with `runtime.now()` so condition timeouts also exclude paused time unless a test explicitly injects another clock.

- [ ] **Step 4: Run focused engine tests**

Run:

```powershell
python -m pytest tests/unit/engine/test_cancellation.py tests/unit/engine/test_runner.py tests/unit/engine/test_wait_logging.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```powershell
git add flow_runner/engine/cancellation.py flow_runner/engine/runner.py flow_runner/engine/step_executor.py tests/unit/engine/test_cancellation.py tests/unit/engine/test_runner.py
git commit -m "feat: unify runtime pause and cancellation"
```

### Task 2: Cancel In-Flight Condition Evaluation

**Files:**

- Modify: `tests/unit/engine/test_step_executor.py`
- Modify: `flow_runner/engine/step_executor.py`

- [ ] **Step 1: Write a failing blocking-condition cancellation test**

```python
@pytest.mark.asyncio
async def test_cancellation_interrupts_condition_evaluation():
    entered = asyncio.Event()
    cleaned_up = asyncio.Event()

    class EmptyConfig(BaseModel):
        pass

    class BlockingCondition:
        name = "test.blocking-condition"
        config_model = EmptyConfig

        async def evaluate(self, config, context):
            del config, context
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                cleaned_up.set()

        def required_resources(self, config):
            del config
            return frozenset()

    registry = CapabilityRegistry()
    registry.register_condition(BlockingCondition())
    token = CancellationToken()
    executor = StepExecutor(
        StepRuntime(registry=registry, context=StepContext(), cancellation=token)
    )
    step = AutomationStep.model_validate(
        {
            "name": "blocking detection",
            "condition": {
                "id": "blocking",
                "capability": BlockingCondition.name,
                "config": {},
            },
        }
    )
    task = asyncio.create_task(executor.execute(step))
    await entered.wait()
    token.cancel()
    result = await asyncio.wait_for(task, timeout=0.2)
    assert result.outcome is StepOutcome.CANCELLED
    assert cleaned_up.is_set()
```

- [ ] **Step 2: Run the test and verify it blocks/fails**

Run:

```powershell
python -m pytest tests/unit/engine/test_step_executor.py::test_cancellation_interrupts_condition_evaluation -q
```

Expected: FAIL or timeout because leaf condition evaluation currently awaits the provider directly.

- [ ] **Step 3: Add one generic cancellable-await helper**

Add a typed `_await_cancellable(awaitable, cancellation)` helper that races the provider task against `wait_cancelled`, cancels pending asyncio tasks, gathers cleanup, and raises `Cancelled` when the token wins. Use it for both condition providers and action providers, preserving existing wait-action started/finished/cancelled logging around the helper.

```python
T = TypeVar("T")


async def _await_cancellable(
    awaitable: Awaitable[T], cancellation: CancellationToken
) -> T:
    operation = asyncio.ensure_future(awaitable)
    cancelled = asyncio.create_task(cancellation.wait_cancelled())
    try:
        done, _ = await asyncio.wait(
            {operation, cancelled}, return_when=asyncio.FIRST_COMPLETED
        )
        if cancelled in done:
            cancellation.raise_if_cancelled()
        return operation.result()
    finally:
        for task in (operation, cancelled):
            if not task.done():
                task.cancel()
        await asyncio.gather(operation, cancelled, return_exceptions=True)
```

Call `await runtime.wait_until_active()` before evaluation and again after the provider returns. A paused provider result may be retained, but no child condition or action may start until resume.

- [ ] **Step 4: Run cancellation and condition tests**

```powershell
python -m pytest tests/unit/engine/test_step_executor.py tests/integration/test_visual_conditions.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```powershell
git add flow_runner/engine/step_executor.py tests/unit/engine/test_step_executor.py
git commit -m "fix: cancel in-flight condition evaluation"
```

### Task 3: Pause-Aware Mouse and Keyboard Checkpoints

**Files:**

- Modify: `tests/integration/test_actions.py`
- Modify: `flow_runner/infrastructure/input/mouse.py`
- Modify: `flow_runner/infrastructure/input/keyboard.py`
- Modify: `flow_runner/capabilities/actions/mouse.py`
- Modify: `flow_runner/app.py`

- [ ] **Step 1: Write failing segmented-input pause tests**

Add tests using a real `CancellationToken` and fake backends. Start a long mouse move and repeated key press, pause after the first emitted event, assert the call list stays unchanged across at least two event-loop turns, resume, and assert all events complete. Also assert `MouseAction` settle delay receives the lifecycle sleep callback.

```python
@pytest.mark.asyncio
async def test_bound_mouse_timing_freezes_segments_while_paused():
    token = CancellationToken()
    calls = []

    class Backend:
        def position(self):
            return (0, 0)

        def moveTo(self, x, y, *, _pause=True):
            calls.append((x, y))

    device = PyAutoGuiMouseDevice(Backend())
    device.bind_timing(token.sleep, token.active_time)
    task = asyncio.create_task(device.move(position=(60, 0), duration=0.1))
    for _ in range(100):
        if calls:
            break
        await asyncio.sleep(0.001)
    assert calls
    token.pause()
    count = len(calls)
    await asyncio.sleep(0.03)
    assert len(calls) == count
    token.resume()
    await asyncio.wait_for(task, timeout=0.3)
    assert calls[-1] == (60, 0)
```

Add the keyboard equivalent explicitly:

```python
@pytest.mark.asyncio
async def test_bound_keyboard_timing_freezes_repeated_keys_while_paused():
    token = CancellationToken()
    calls = []

    class Backend:
        def press(self, key, presses, interval):
            calls.append((key, presses, interval))

    device = PyAutoGuiKeyboardDevice(Backend())
    device.bind_timing(token.sleep)
    task = asyncio.create_task(device.press("a", 3, 0.05))
    for _ in range(100):
        if calls:
            break
        await asyncio.sleep(0.001)
    assert len(calls) == 1
    token.pause()
    await asyncio.sleep(0.03)
    assert len(calls) == 1
    token.resume()
    await asyncio.wait_for(task, timeout=0.3)
    assert len(calls) == 3
```

Add a recording-playback checkpoint test using the same token:

```python
@pytest.mark.asyncio
async def test_recording_playback_freezes_between_events_while_paused(tmp_path):
    path = tmp_path / "recording.json"
    RecordingStore.save(
        path,
        [
            RecordedEvent(timestamp=0.0, kind="move", data={"x": 1, "y": 2}),
            RecordedEvent(
                timestamp=0.1,
                kind="click",
                data={"x": 1, "y": 2, "button": "left"},
            ),
            RecordedEvent(timestamp=0.2, kind="move", data={"x": 3, "y": 4}),
        ],
    )
    token = CancellationToken()
    calls = []

    class Backend:
        def moveTo(self, x, y):
            calls.append(("move", x, y))

        def click(self, **kwargs):
            calls.append(("click", kwargs))

    task = asyncio.create_task(
        RecordingPlayer(
            sleep=token.sleep,
            clock=token.active_time,
            backend=Backend(),
        )(
            path, speed=1.0, max_gap=1.0
        )
    )
    for _ in range(100):
        if calls:
            break
        await asyncio.sleep(0.001)
    assert calls == [("move", 1, 2)]
    token.pause()
    await asyncio.sleep(0.03)
    assert calls == [("move", 1, 2)]
    token.resume()
    for _ in range(200):
        if len(calls) >= 2:
            break
        await asyncio.sleep(0.001)
    assert [call[0] for call in calls] == ["move", "click"]
    await asyncio.sleep(0.03)
    assert [call[0] for call in calls] == ["move", "click"]
    await asyncio.wait_for(task, timeout=0.3)
    assert [call[0] for call in calls] == ["move", "click", "move"]
```

- [ ] **Step 2: Run tests and verify continued input while paused**

```powershell
python -m pytest tests/integration/test_actions.py -k "freezes_segments_while_paused or settle_delay" -q
```

Expected: FAIL because mouse/keyboard interval sleeps are still plain `asyncio.sleep` and devices have no lifecycle binding.

- [ ] **Step 3: Bind per-run timing without replacing shared input state**

Add `bind_timing(sleep, clock)` to `PyAutoGuiMouseDevice` and `bind_timing(sleep)` to `PyAutoGuiKeyboardDevice`. Replace every interval `asyncio.sleep` in these devices with `self.sleep`. Keep held-button and held-key sets on the original shared device so termination release still works.

In `create_application.step_executor_factory`, call optional binders before building the execution registry:

```python
mouse_binder = getattr(mouse, "bind_timing", None)
if callable(mouse_binder):
    mouse_binder(token.sleep, token.active_time)
keyboard_binder = getattr(keyboard, "bind_timing", None)
if callable(keyboard_binder):
    keyboard_binder(token.sleep)
```

Extend `_build_registry` with an injected `clock` callback that defaults to `monotonic`. The execution registry passes `clock=token.active_time`; the validation registry retains the normal default. Pass `sleep=token.sleep` to `MouseAction` and construct `RecordingPlayer(sleep=sleep, clock=clock)`. This prevents a long pause from compressing later playback events after resume. Keep feature-injected test devices compatible by making timing binders optional.

- [ ] **Step 4: Run input action tests**

```powershell
python -m pytest tests/integration/test_actions.py tests/unit/engine/test_step_executor.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

```powershell
git add flow_runner/infrastructure/input/mouse.py flow_runner/infrastructure/input/keyboard.py flow_runner/capabilities/actions/mouse.py flow_runner/app.py tests/integration/test_actions.py
git commit -m "feat: pause segmented input at lifecycle checkpoints"
```

### Task 4: Pause and Stop the Independent Recorder

**Files:**

- Modify: `tests/integration/test_actions.py`
- Modify: `flow_runner/infrastructure/input/recording.py`

- [ ] **Step 1: Write recorder pause/resume and failure-cleanup tests**

Use a mutable fake clock and listener. Verify events during pause are ignored, resumed timestamps subtract paused time, repeated pause/resume is idempotent, and stop while paused writes pre-pause events. Add a save-failure test proving `listener.stop()` ran and `is_recording` is false.

```python
def test_recording_recorder_excludes_paused_input_and_time(tmp_path):
    now = 10.0
    callbacks = {}

    class Listener:
        def __init__(self):
            self.started = False
            self.stopped = False

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

    listener = Listener()
    recorder = RecordingRecorder(
        listener_factory=lambda **provided: callbacks.update(provided) or listener,
        clock=lambda: now,
    )
    recorder.start()
    now = 11.0
    callbacks["on_press"]("a")
    recorder.pause()
    now = 16.0
    callbacks["on_press"]("ignored")
    recorder.resume()
    now = 17.0
    callbacks["on_press"]("b")
    events = recorder.stop(tmp_path / "recording.json")
    assert [event.data["key"] for event in events] == ["a", "b"]
    assert [event.timestamp for event in events] == pytest.approx([1.0, 2.0])
```

- [ ] **Step 2: Run tests and verify missing pause API**

```powershell
python -m pytest tests/integration/test_actions.py -k "recording_recorder" -q
```

Expected: FAIL because `RecordingRecorder` has no pause state.

- [ ] **Step 3: Implement recorder lifecycle state**

Add `_paused_at` and `_paused_total`, an `is_paused` property, and idempotent `pause`/`resume` methods protected by the existing lock. `_append` returns immediately while paused and computes `clock - started_at - paused_total`. `start` resets pause state. `stop` must stop and detach the listener before saving so an `OSError` cannot leave recording active.

- [ ] **Step 4: Run recorder and playback tests**

```powershell
python -m pytest tests/integration/test_actions.py -k "recording_player or recording_recorder" -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 4**

```powershell
git add flow_runner/infrastructure/input/recording.py tests/integration/test_actions.py
git commit -m "feat: pause and safely stop input recording"
```

### Task 5: Unify Qt Pause and Stop Entry Points

**Files:**

- Modify: `tests/ui/test_runner_bridge.py`
- Modify: `tests/ui/test_main_window.py`
- Modify: `tests/ui/test_app_smoke.py`
- Modify: `flow_runner/ui/runner_bridge.py`
- Modify: `flow_runner/ui/main_window.py`
- Modify: `flow_runner/app.py`

- [ ] **Step 1: Write acceptance-signal and application coordination tests**

Add bridge assertions that accepted starts return `True`, duplicate starts return `False`, and pause/resume/stop return `False` when no runtime loop can accept them:

```python
def test_runner_bridge_reports_request_acceptance(qtbot):
    workflow = Workflow(name="main", steps=[AutomationStep(name="step")])
    project = Project(name="p", groups=[FlowGroup(name="g", workflows=[workflow])])
    bridge = RunnerBridge(Runner(ImmediateExecutor()))
    with qtbot.waitSignal(bridge.finished, timeout=3000):
        assert bridge.start(project, workflow.id) is True
    assert bridge.pause() is False
    assert bridge.resume() is False
    assert bridge.stop() is False


def test_runner_bridge_rejected_start_returns_false(qtbot):
    workflow = Workflow(name="main")
    project = Project(name="p", groups=[FlowGroup(name="g", workflows=[workflow])])
    bridge = RunnerBridge(Runner(ImmediateExecutor()))
    bridge._running = True
    with qtbot.waitSignal(bridge.failed, timeout=1000):
        assert bridge.start(project, workflow.id) is False
```

Add `MainWindow` tests with a fake bridge returning booleans. Assert `runtimePauseChanged(True)`, `runtimePauseChanged(False)`, and `runtimeStopAccepted` emit only after the bridge returns `True`, for both QAction and existing hotkey signals:

Extend the test module's enum import to include `RunnerState`.

```python
class LifecycleBridge:
    def __init__(self, accepted=True):
        self.eventReceived = _FakeSignal()
        self.failed = _FakeSignal()
        self.is_running = True
        self.accepted = accepted

    def pause(self):
        return self.accepted

    def resume(self):
        return self.accepted

    def stop(self):
        return self.accepted


def test_main_window_emits_only_accepted_runtime_controls(qtbot):
    bridge = LifecycleBridge()
    window = MainWindow(sample_project(), runner_bridge=bridge)
    qtbot.addWidget(window)
    window.run_view_model.state = RunnerState.RUNNING
    window._update_runtime_actions(RunnerState.RUNNING)
    with qtbot.waitSignal(window.runtimePauseChanged) as paused:
        window.pause_action.trigger()
    assert paused.args == [True]

    window.run_view_model.state = RunnerState.PAUSED
    window._update_runtime_actions(RunnerState.PAUSED)
    with qtbot.waitSignal(window.runtimePauseChanged) as resumed:
        window.pauseRequested.emit()
    assert resumed.args == [False]

    with qtbot.waitSignal(window.runtimeStopAccepted):
        window.stopRequested.emit()


def test_main_window_suppresses_rejected_runtime_controls(qtbot):
    window = MainWindow(sample_project(), runner_bridge=LifecycleBridge(False))
    qtbot.addWidget(window)
    pause_events = []
    stop_events = []
    window.runtimePauseChanged.connect(pause_events.append)
    window.runtimeStopAccepted.connect(lambda: stop_events.append(True))
    window.run_view_model.state = RunnerState.RUNNING
    window._update_runtime_actions(RunnerState.RUNNING)
    window.pause_action.trigger()
    window.stop_action.trigger()
    assert pause_events == []
    assert stop_events == []
```

Add one application smoke test with a 60-second wait workflow and fake recording listener:

Extend `tests/ui/test_app_smoke.py`'s enum import to include `RunnerState`.

```python
def test_application_pause_and_stop_coordinate_active_recording(qtbot, tmp_path):
    callbacks = {}

    class Listener:
        def __init__(self):
            self.started = False
            self.stopped = False

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

    listener = Listener()

    def recording_factory(**provided):
        callbacks.update(provided)
        return listener

    workflow = Workflow(
        name="main",
        steps=[
            AutomationStep(
                name="wait",
                actions=[{"capability": "system.wait", "config": {"seconds": 60}}],
            )
        ],
    )
    project_path = tmp_path / "project.json"
    ProjectStore(project_path).save(
        Project(name="p", groups=[FlowGroup(name="g", workflows=[workflow])])
    )
    recording_path = tmp_path / "latest.json"
    composition = create_application(
        [],
        project_path=project_path,
        recording_listener_factory=recording_factory,
        recording_path=recording_path,
    )
    qtbot.addWidget(composition.window)
    composition.window.record_action.trigger()
    callbacks["on_press"]("a")
    with qtbot.waitSignal(composition.runner_bridge.eventReceived, timeout=3000):
        composition.window.start_action.trigger()

    composition.window.pause_action.trigger()
    qtbot.waitUntil(lambda: composition.runner.state is RunnerState.PAUSED)
    assert composition.recorder.is_paused
    callbacks["on_press"]("ignored")

    composition.window.pause_action.trigger()
    qtbot.waitUntil(lambda: composition.runner.state is RunnerState.RUNNING)
    assert not composition.recorder.is_paused
    callbacks["on_press"]("b")

    with qtbot.waitSignal(composition.runner_bridge.terminated, timeout=3000):
        composition.window.stop_action.trigger()
    assert listener.stopped
    assert recording_path.exists()
    assert composition.window.record_action.text() == "录制"
    composition.shutdown()
```

Add the natural-completion boundary explicitly:

```python
def test_natural_runtime_completion_leaves_independent_recording_active(qtbot, tmp_path):
    class Listener:
        def __init__(self):
            self.stopped = False

        def start(self):
            pass

        def stop(self):
            self.stopped = True

    listener = Listener()
    workflow = Workflow(name="main")
    project_path = tmp_path / "project.json"
    ProjectStore(project_path).save(
        Project(name="p", groups=[FlowGroup(name="g", workflows=[workflow])])
    )
    composition = create_application(
        [],
        project_path=project_path,
        recording_listener_factory=lambda **callbacks: listener,
        recording_path=tmp_path / "latest.json",
    )
    qtbot.addWidget(composition.window)
    composition.window.record_action.trigger()
    with qtbot.waitSignal(composition.runner_bridge.finished, timeout=3000):
        composition.window.start_action.trigger()
    assert composition.recorder.is_recording
    assert not listener.stopped
    composition.window.record_action.trigger()
    composition.shutdown()
```

- [ ] **Step 2: Run tests and verify missing acceptance signals**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_runner_bridge.py tests/ui/test_main_window.py tests/ui/test_app_smoke.py -k "accept or coordinate_active_recording" -q
```

Expected: FAIL because bridge methods return `None` and the window exposes no accepted lifecycle signals.

- [ ] **Step 3: Implement accepted lifecycle propagation**

Make `_start_thread` and public start methods return `bool`. Return `False` after posting the existing duplicate-run error; return `True` only after the runtime thread is created. Make pause/resume/stop return `False` when `_loop` is unavailable, otherwise schedule the runner operation and return `True`.

Add these signals to `MainWindow`:

```python
runtimePauseChanged = Signal(bool)
runtimeStopAccepted = Signal()
```

`_toggle_pause` emits the matching boolean only when bridge pause/resume returns true. `_stop_runtime` emits only when bridge stop returns true. Toolbar actions and F7/F8 already converge on these two methods, so retain that single path.

Add composition methods that pause/resume an active recorder and stop/save it after accepted stop. Catch save errors, set recording UI state false, and show `录制保存失败：...`; never suppress runtime stop or input release. Connect the new window signals after constructing `ApplicationComposition`.

- [ ] **Step 4: Run Qt lifecycle tests**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_runner_bridge.py tests/ui/test_main_window.py tests/ui/test_app_smoke.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 5**

```powershell
git add flow_runner/ui/runner_bridge.py flow_runner/ui/main_window.py flow_runner/app.py tests/ui/test_runner_bridge.py tests/ui/test_main_window.py tests/ui/test_app_smoke.py
git commit -m "fix: coordinate runtime and recorder lifecycle"
```

### Task 6: Minimize Only After an Accepted Workflow Start

**Files:**

- Modify: `tests/ui/test_app_smoke.py`
- Modify: `tests/ui/test_main_window.py`
- Modify: `flow_runner/ui/dialogs/settings_dialog.py`
- Modify: `flow_runner/ui/main_window.py`

- [ ] **Step 1: Write failing settings and minimization tests**

Add dialog tests for missing, invalid, true, and false values. The checkbox is checked only when the stored value `is True`; `project_settings()` always emits a boolean:

```python
@pytest.mark.parametrize(
    ("settings", "expected"),
    [
        ({}, False),
        ({"minimize_on_workflow_start": "true"}, False),
        ({"minimize_on_workflow_start": False}, False),
        ({"minimize_on_workflow_start": True}, True),
    ],
)
def test_settings_dialog_round_trips_minimize_on_workflow_start(qtbot, settings, expected):
    dialog = SettingsDialog(HotkeyConfig(), settings)
    qtbot.addWidget(dialog)
    assert dialog.minimize_on_start_check.isChecked() is expected
    stored = dialog.project_settings()["minimize_on_workflow_start"]
    assert stored is expected
    assert isinstance(stored, bool)
```

Add visible-window tests with a fake accepting bridge:

```python
class AcceptingBridge:
    def __init__(self, accepted):
        self.eventReceived = _FakeSignal()
        self.failed = _FakeSignal()
        self.is_running = False
        self.accepted = accepted
        self.started = []

    def start(self, project, workflow_id):
        del project
        self.started.append(workflow_id)
        return self.accepted

    def start_parallel(self, project, block_id):
        del project
        self.started.append(block_id)
        return self.accepted


def test_accepted_workflow_start_minimizes_when_enabled(qtbot):
    project = sample_project().model_copy(
        update={"settings": {"minimize_on_workflow_start": True}}
    )
    bridge = AcceptingBridge(accepted=True)
    window = MainWindow(project, runner_bridge=bridge)
    qtbot.addWidget(window)
    window.show()
    window.start_action.trigger()
    assert window.isMinimized()


def test_rejected_start_does_not_minimize(qtbot):
    project = sample_project().model_copy(
        update={"settings": {"minimize_on_workflow_start": True}}
    )
    window = MainWindow(project, runner_bridge=AcceptingBridge(accepted=False))
    qtbot.addWidget(window)
    window.show()
    window.start_action.trigger()
    assert not window.isMinimized()
```

Cover parallel-block start and `startRequested.emit()` to prove the hotkey path uses the same logic. Assert selected-step run and condition preview never minimize.

Add a real bridge regression proving completion does not restore the window:

```python
def test_completed_minimized_run_stays_minimized(qtbot):
    workflow = Workflow(name="main")
    project = Project(
        name="p",
        groups=[FlowGroup(name="g", workflows=[workflow])],
        settings={"minimize_on_workflow_start": True},
    )
    bridge = RunnerBridge(Runner(ImmediateExecutor()))
    window = MainWindow(project, runner_bridge=bridge)
    qtbot.addWidget(window)
    window.show()
    with qtbot.waitSignal(bridge.finished, timeout=3000):
        window.startRequested.emit()
    assert window.isMinimized()
```

- [ ] **Step 2: Run tests and verify failures**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_main_window.py tests/ui/test_app_smoke.py -k "minimize_on_workflow_start or accepted_workflow_start or rejected_start" -q
```

Expected: FAIL because the checkbox and post-acceptance minimize logic do not exist.

- [ ] **Step 3: Implement the project setting and accepted-start behavior**

In `SettingsDialog`, create `self.minimize_on_start_check = QCheckBox("启动流程后最小化")`, set it with `settings.get("minimize_on_workflow_start") is True`, add it as the `运行行为` row, and include its `isChecked()` value in `project_settings()`.

In `_start_selected_workflow`, capture the bridge return value for both normal and parallel runs. Call `showMinimized()` only when accepted and the current view-model setting is exactly `True`. Do not apply this logic to selected-step execution or preview.

- [ ] **Step 4: Run settings and start-path tests**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_main_window.py tests/ui/test_app_smoke.py tests/ui/test_simple_shell.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit Task 6**

```powershell
git add flow_runner/ui/dialogs/settings_dialog.py flow_runner/ui/main_window.py tests/ui/test_main_window.py tests/ui/test_app_smoke.py
git commit -m "feat: minimize after accepted workflow start"
```

### Task 7: High-Contrast Application, Command, and Tree Icons

**Files:**

- Create: `flow_runner/ui/icons.py`
- Create: `flow_runner/infrastructure/windowing/identity.py`
- Create: `flow_runner/resources/icons/app.svg`
- Create: `flow_runner/resources/icons/branch-open.svg`
- Create: `flow_runner/resources/icons/branch-closed.svg`
- Create: `flow_runner/resources/icons/start.svg`, `pause.svg`, `resume.svg`, `stop.svg`, `record.svg`, `save.svg`, `undo.svg`, `settings.svg`, `diagnostics.svg`, `add.svg`, `copy.svg`, `edit.svg`, `delete.svg`, `move-up.svg`, `move-down.svg`, `move-group.svg`, `preview.svg`, `template.svg`
- Create: `tests/ui/test_icons.py`
- Create: `tests/unit/infrastructure/test_window_identity.py`
- Modify: `flow_runner/ui/main_window.py`
- Modify: `flow_runner/ui/widgets/responsive_controls.py`
- Modify: `flow_runner/ui/theme_manager.py`
- Modify: `flow_runner/resources/styles/base.qss`
- Modify: `flow_runner/app.py`
- Modify: `tests/ui/test_theme_manager.py`
- Modify: `tests/unit/test_package.py`

- [ ] **Step 1: Write failing icon, style, and Windows identity tests**

Test that every declared icon exists and `QIcon.isNull()` is false, the application icon is set by `create_application`, all common MainWindow actions have non-null icons, and the pause action changes between pause/resume icons with runner state. Test responsive buttons use `ToolButtonTextBesideIcon`.

```python
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QToolButton

from flow_runner.domain.enums import RunnerState
from flow_runner.ui.icons import ACTION_ICON_NAMES, application_icon, icon


def test_declared_icons_are_loadable():
    assert not application_icon().isNull()
    for name in set(ACTION_ICON_NAMES.values()):
        assert not icon(name).isNull(), name


def test_main_window_common_actions_keep_text_and_icons(qtbot):
    window = MainWindow(sample_project())
    qtbot.addWidget(window)
    actions = {
        action.objectName(): action
        for action in window.findChildren(QAction)
        if action.objectName() in ACTION_ICON_NAMES
    }
    assert set(actions) == set(ACTION_ICON_NAMES)
    assert all(action.text() and not action.icon().isNull() for action in actions.values())
    buttons = window.findChildren(QToolButton)
    assert buttons
    assert all(
        button.toolButtonStyle() is Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        for button in buttons
        if button.defaultAction() in actions.values()
    )


def test_pause_action_switches_to_resume_icon(qtbot):
    window = MainWindow(sample_project())
    qtbot.addWidget(window)
    pause_key = window.pause_action.icon().cacheKey()
    window._update_runtime_actions(RunnerState.PAUSED)
    assert window.pause_action.text() == "继续"
    assert window.pause_action.icon().cacheKey() != pause_key
```

Extend the theme test to require branch selectors and verify `ThemeManager` replaces `__ICON_DIR__` with an absolute forward-slash path. Add package-resource assertions with `importlib.resources.files("flow_runner")`.

```python
def test_packaged_icon_resources_are_present():
    from importlib.resources import files

    icon_root = files("flow_runner").joinpath("resources", "icons")
    for name in ("app.svg", "branch-open.svg", "branch-closed.svg"):
        assert icon_root.joinpath(name).is_file()
```

Use an injected identity API following the existing DPI-test pattern:

```python
def test_windows_identity_sets_stable_application_id():
    calls = []
    result = set_windows_app_user_model_id(
        platform="win32", api=lambda value: calls.append(value) or 0
    )
    assert result is True
    assert calls == ["FlowRunner.Qt"]


def test_windows_identity_is_noop_off_windows():
    calls = []
    assert not set_windows_app_user_model_id(platform="linux", api=calls.append)
    assert calls == []
```

- [ ] **Step 2: Run tests and verify missing resources**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_icons.py tests/ui/test_theme_manager.py tests/unit/infrastructure/test_window_identity.py tests/unit/test_package.py -q
```

Expected: FAIL because the helper, identity module, assets, and branch selectors do not exist.

- [ ] **Step 3: Create exact SVG resource set**

Use this wrapper for command and branch assets, inserting the listed body exactly:

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
  <!-- body from the mapping below -->
</svg>
```

Bodies:

```text
branch-open.svg:   <path fill="#a9bbff" d="M4 7h16l-8 10z"/>
branch-closed.svg: <path fill="#a9bbff" d="M7 4v16l10-8z"/>
start.svg:         <path fill="#45d9a2" d="M7 4v16l13-8z"/>
resume.svg:        <path fill="#45d9a2" d="M7 4v16l13-8z"/>
pause.svg:         <path fill="#e7eaf4" d="M6 4h4v16H6zm8 0h4v16h-4z"/>
stop.svg:          <path fill="#ff7070" d="M5 5h14v14H5z"/>
record.svg:        <circle fill="#ff7070" cx="12" cy="12" r="7"/>
save.svg:          <path fill="#e7eaf4" d="M4 3h13l3 3v15H4zm3 2v6h10V6.8L15.2 5zm1 10v4h8v-4z"/>
undo.svg:          <path fill="none" stroke="#e7eaf4" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M9 7 4 12l5 5v-3h5a5 5 0 0 0 5-5 5 5 0 0 0-5-5h-2"/>
settings.svg:      <path fill="none" stroke="#e7eaf4" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8Zm0-5v2m0 14v2M3 12h2m14 0h2M5.6 5.6 7 7m10 10 1.4 1.4M18.4 5.6 17 7M7 17l-1.4 1.4"/>
diagnostics.svg:   <path fill="none" stroke="#e7eaf4" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M3 12h4l2-6 4 12 2-6h6"/>
add.svg:           <path fill="#e7eaf4" d="M11 4h2v7h7v2h-7v7h-2v-7H4v-2h7z"/>
copy.svg:          <path fill="none" stroke="#e7eaf4" stroke-width="2" d="M8 8h11v11H8zM5 16H3V3h13v2"/>
edit.svg:          <path fill="#e7eaf4" d="m4 17.3-.7 3.4 3.4-.7L18.8 7.9l-2.7-2.7zM18.2 3.1l2.7 2.7-1.2 1.2L17 4.3z"/>
delete.svg:        <path fill="#ff7070" d="M7 7h10l-1 14H8zm2-4h6l1 2h4v2H4V5h4z"/>
move-up.svg:       <path fill="#e7eaf4" d="m12 4 7 8h-5v8h-4v-8H5z"/>
move-down.svg:     <path fill="#e7eaf4" d="m12 20-7-8h5V4h4v8h5z"/>
move-group.svg:    <path fill="#e7eaf4" d="M4 6h7v4h9v4h-9v4z"/>
preview.svg:       <path fill="none" stroke="#e7eaf4" stroke-width="2" d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"/><circle fill="#e7eaf4" cx="12" cy="12" r="3"/>
template.svg:      <path fill="none" stroke="#e7eaf4" stroke-width="2" d="M4 4h7v7H4zm9 0h7v7h-7zM4 13h7v7H4zm9 0h7v7h-7z"/>
```

Create `app.svg` with a 64x64 dark square, three light-blue workflow nodes, connecting lines, and a white play triangle:

```xml
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect x="2" y="2" width="60" height="60" rx="12" fill="#17213b"/>
  <path d="M13 17h13m-13 15h13m-13 15h13" stroke="#45d9a2" stroke-width="4" stroke-linecap="round"/>
  <circle cx="12" cy="17" r="5" fill="#a9bbff"/>
  <circle cx="12" cy="32" r="5" fill="#a9bbff"/>
  <circle cx="12" cy="47" r="5" fill="#a9bbff"/>
  <path d="M29 17v30l24-15z" fill="#ffffff"/>
</svg>
```

- [ ] **Step 4: Implement icon loading, action mapping, and branch styling**

Create `flow_runner/ui/icons.py` with `ICON_DIRECTORY`, `icon(name)`, `application_icon()`, and a constant action mapping. Missing files return `QIcon()`.

```python
ICON_DIRECTORY = Path(__file__).resolve().parents[1] / "resources" / "icons"

ACTION_ICON_NAMES = {
    "saveProjectAction": "save",
    "undoProjectAction": "undo",
    "addStepAction": "add",
    "addTemplateStepAction": "template",
    "removeStepAction": "delete",
    "moveStepUpAction": "move-up",
    "moveStepDownAction": "move-down",
    "addGroupAction": "add",
    "copyGroupAction": "copy",
    "addWorkflowAction": "add",
    "copyWorkflowAction": "copy",
    "renameFlowAction": "edit",
    "moveWorkflowUpAction": "move-up",
    "moveWorkflowDownAction": "move-down",
    "moveWorkflowGroupAction": "move-group",
    "deleteFlowAction": "delete",
    "projectSettingsAction": "settings",
    "addParallelBlockAction": "add",
    "editParallelBlockAction": "edit",
    "deleteParallelBlockAction": "delete",
    "copyStepAction": "copy",
    "startWorkflowAction": "start",
    "pauseWorkflowAction": "pause",
    "stopWorkflowAction": "stop",
    "recordAction": "record",
    "diagnosticsAction": "diagnostics",
    "runSelectedStepAction": "start",
    "previewConditionAction": "preview",
}
```

After all actions are created, apply mapping by `objectName`. In `_update_runtime_actions`, switch the pause action between `pause` and `resume` together with its Chinese text. Set `ToolButtonTextBesideIcon` in `ResponsiveControlGroup.add_action` so labels remain visible.

Add these central QSS rules:

```css
QTreeWidget::branch:has-children:closed {
    image: url("__ICON_DIR__/branch-closed.svg");
}

QTreeWidget::branch:has-children:open {
    image: url("__ICON_DIR__/branch-open.svg");
}
```

`ThemeManager.apply` replaces `__ICON_DIR__` with `path.parent.parent.joinpath("icons").as_posix()` before setting the stylesheet.

- [ ] **Step 5: Implement application identity and icon startup**

Create `set_windows_app_user_model_id(app_id="FlowRunner.Qt", *, platform=None, api=None) -> bool`. Off Windows return false. On Windows call the injected API or `ctypes.WinDLL("shell32").SetCurrentProcessExplicitAppUserModelID`; catch `AttributeError`, `OSError`, and `TypeError` and return false.

In `create_application`, call identity setup before constructing `QApplication`, then set `app.setWindowIcon(application_icon())` and `window.setWindowIcon(app.windowIcon())`. Icon failure must not abort startup.

- [ ] **Step 6: Run icon and UI tests**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_icons.py tests/ui/test_theme_manager.py tests/ui/test_main_window.py tests/unit/infrastructure/test_window_identity.py tests/unit/test_package.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit Task 7**

```powershell
git add flow_runner/resources/icons flow_runner/resources/styles/base.qss flow_runner/ui/icons.py flow_runner/ui/theme_manager.py flow_runner/ui/widgets/responsive_controls.py flow_runner/ui/main_window.py flow_runner/infrastructure/windowing/identity.py flow_runner/app.py tests/ui/test_icons.py tests/ui/test_theme_manager.py tests/ui/test_main_window.py tests/unit/infrastructure/test_window_identity.py tests/unit/test_package.py
git commit -m "feat: add high-contrast application and command icons"
```

### Task 8: Documentation and Complete Verification

**Files:**

- Modify: `README.md`

- [ ] **Step 1: Update user-facing behavior documentation**

In `README.md`, document:

- `设置 -> 启动流程后最小化`, default off and project-scoped;
- accepted toolbar/F6 workflow and parallel starts minimize, while step run/preview do not;
- the window does not auto-restore;
- F8 freezes built-in detection/input checkpoints, playback, waits, and active recording timestamps;
- F7 cancels runtime work, saves/stops active recording, and releases held inputs;
- atomic OS calls and previously launched processes cannot be reversed;
- application, command, and flow-tree icons use packaged high-contrast assets.

- [ ] **Step 2: Run formatting and focused regression suites**

```powershell
python -m ruff format flow_runner tests
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/unit/engine tests/integration/test_actions.py tests/ui/test_runner_bridge.py tests/ui/test_main_window.py tests/ui/test_app_smoke.py tests/ui/test_icons.py tests/ui/test_theme_manager.py -q
```

Expected: PASS.

- [ ] **Step 3: Run the full quality gate with global Python**

Run each command separately and retain its output:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest
python -m ruff check .
python -m ruff format --check .
python -m mypy flow_runner
python -m compileall flow_runner start_flow_runner.pyw
python -m pip check
```

Expected: every command exits 0. Record the actual pytest count in the final handoff; do not predict or hard-code it in README.

- [ ] **Step 4: Perform diff and worktree safety review**

```powershell
git status --short
git diff --check
git diff --stat
git diff -- data/project.json
```

Expected: no `data/project.json` diff in the isolated implementation worktree; only files named in this plan are changed.

- [ ] **Step 5: Commit documentation**

```powershell
git add README.md
git commit -m "docs: describe runtime controls and icon behavior"
```

- [ ] **Step 6: Run manual Windows acceptance**

Launch with global Python:

```powershell
python -m flow_runner.app
```

Verify the six manual checks from `docs/superpowers/specs/2026-07-16-runtime-control-and-icons-design.md`: title/taskbar/Alt+Tab icon, command and branch visibility, accepted-start minimization, no automatic restore, F8 freeze/resume, and F7 stop/save/release. Report these as manual checks; do not claim them passed until actually observed.

---

## Completion Criteria

- All eight task commits exist and contain only scoped files.
- The full global-Python quality gate passes.
- No user project data is staged or changed.
- Manual Windows checks are either passed by the user or explicitly handed off as remaining acceptance.
- Do not merge, push, tag, or bump the version unless the user separately requests it.

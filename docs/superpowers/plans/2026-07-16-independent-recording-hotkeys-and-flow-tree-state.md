# Independent Recording Hotkeys and Flow-Tree State Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add fully independent recording pause/resume controls, apply hotkey changes immediately, exclude every effective control hotkey from recordings, and remember collapsed flow groups locally per project.

**Architecture:** `HotkeyService` owns effective runtime bindings and listener replacement; `RecordingRecorder` filters keys at ingestion and owns only recording timing/state. `MainWindow` exposes independent recording actions and settings signals, while `ApplicationComposition` coordinates services without coupling workflow pause to recorder pause. A separate `FlowTreePreferences` wrapper stores collapsed group UUIDs in local `QSettings` and `FlowTreePanel` reports expansion changes without touching the project model.

**Tech Stack:** Python 3.12, PySide6 signals/actions/QSettings, pynput listener adapters, Pydantic, pytest/pytest-qt/pytest-asyncio, Ruff, mypy.

---

## Safety and Workspace Rules

- The current branch is `feature-region-picker-dark-ui`.
- `data/project.json` contains user acceptance changes and must never be staged, rewritten, copied,
  reverted, or included in any task commit.
- Use global `python` for every command.
- Follow RED -> verify expected failure -> GREEN -> focused verification -> commit for every task.
- Before every commit run `git diff --cached --name-only` and verify that `data/project.json` is absent.

### Task 1: Runtime-Reconfigurable Hotkey Service

**Files:**

- Modify: `flow_runner/ui/hotkeys.py`
- Modify: `tests/ui/test_app_smoke.py`

- [ ] **Step 1: Add failing configuration and listener-replacement tests**

Extend the existing hotkey tests in `tests/ui/test_app_smoke.py`:

```python
def test_record_pause_hotkey_defaults_to_disabled():
    config = HotkeyConfig()
    assert config.record_pause == ""
    assert "" not in config.enabled_bindings()


def test_record_pause_hotkey_participates_in_duplicate_validation():
    with pytest.raises(ValidationError, match="duplicate"):
        HotkeyConfig(record="F9", record_pause="F9")


def test_hotkey_service_reconfigures_active_listener_immediately():
    calls = []
    listeners = []

    class Listener:
        def __init__(self, on_press):
            self.on_press = on_press
            self.started = False
            self.stopped = False

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

    def factory(on_press):
        listener = Listener(on_press)
        listeners.append(listener)
        return listener

    service = HotkeyService(
        HotkeyConfig(start="F6", stop="", pause="", record=""),
        actions={
            "start": lambda: calls.append("start"),
            "record_pause": lambda: calls.append("record_pause"),
        },
        listener_factory=factory,
    )
    service.start()
    service.reconfigure(
        HotkeyConfig(
            start="",
            stop="",
            pause="",
            record="",
            record_pause="F10",
        )
    )

    assert listeners[0].stopped
    assert listeners[1].started
    listeners[1].on_press("f10")
    assert calls == ["record_pause"]
    assert service.control_keys == frozenset({"F10"})
```

Add coverage for reconfiguring before `start()` and changing to all-empty bindings while active:

```python
def test_hotkey_service_reconfigure_before_start_uses_new_bindings():
    listeners = []

    class Listener:
        def __init__(self, on_press):
            self.on_press = on_press

        def start(self):
            pass

        def stop(self):
            pass

    service = HotkeyService(
        HotkeyConfig(start="F6", stop="", pause="", record=""),
        actions={},
        listener_factory=lambda on_press: listeners.append(Listener(on_press))
        or listeners[-1],
    )
    service.reconfigure(
        HotkeyConfig(start="F11", stop="", pause="", record="")
    )
    service.start()
    assert service.control_keys == frozenset({"F11"})
    assert len(listeners) == 1


def test_active_hotkey_service_can_remove_all_bindings():
    listeners = []

    class Listener:
        def __init__(self, on_press):
            self.on_press = on_press
            self.stopped = False

        def start(self):
            pass

        def stop(self):
            self.stopped = True

    service = HotkeyService(
        HotkeyConfig(start="F6", stop="", pause="", record=""),
        actions={},
        listener_factory=lambda on_press: listeners.append(Listener(on_press))
        or listeners[-1],
    )
    service.start()
    service.reconfigure(
        HotkeyConfig(start="", stop="", pause="", record="")
    )
    assert listeners[0].stopped
    assert service.control_keys == frozenset()
    assert service.listener is None
```

Add listener-start failure coverage restoring the old binding set:

```python
def test_hotkey_service_rolls_back_bindings_when_replacement_listener_fails():
    created = 0

    class Listener:
        def __init__(self, fail=False):
            self.fail = fail

        def start(self):
            if self.fail:
                raise OSError("listener failed")

        def stop(self):
            pass

    def factory(on_press):
        del on_press
        nonlocal created
        created += 1
        return Listener(fail=created == 2)

    service = HotkeyService(
        HotkeyConfig(start="F6", stop="", pause="", record=""),
        actions={},
        listener_factory=factory,
    )
    service.start()
    with pytest.raises(OSError, match="listener failed"):
        service.reconfigure(
            HotkeyConfig(start="F11", stop="", pause="", record="")
        )
    assert service.control_keys == frozenset({"F6"})
```

- [ ] **Step 2: Run tests and verify RED**

```powershell
python -m pytest tests/ui/test_app_smoke.py -k "record_pause_hotkey or reconfigures_active_listener or rolls_back_bindings" -q
```

Expected: FAIL because `record_pause`, `reconfigure`, and `control_keys` do not exist.

- [ ] **Step 3: Implement the configuration field and service lifecycle**

In `HotkeyConfig`, add the field and include it in the existing validators:

```python
record_pause: str = ""

@field_validator("start", "stop", "pause", "record", "record_pause", mode="before")
```

Keep `enabled_bindings()` as the stable key-to-action mapping. In `HotkeyService`, add an active
flag, a property, listener helpers, and rollback-aware reconfiguration:

```python
class HotkeyService:
    def __init__(...):
        ...
        self._active = False

    @property
    def control_keys(self) -> frozenset[str]:
        return frozenset(self.bindings)

    def start(self) -> None:
        if self._active:
            return
        self._active = True
        self._start_listener()

    def stop(self) -> None:
        self._active = False
        self._stop_listener()

    def reconfigure(self, config: HotkeyConfig) -> None:
        replacement = config.enabled_bindings()
        previous = dict(self.bindings)
        if not self._active:
            self.bindings = replacement
            return
        self._stop_listener()
        self.bindings = replacement
        try:
            self._start_listener()
        except Exception:
            self.bindings = previous
            try:
                self._start_listener()
            except Exception:
                pass
            raise

    def _start_listener(self) -> None:
        if self.listener is not None or not self.bindings:
            return
        listener = self.listener_factory(self._on_press)
        listener.start()
        self.listener = listener

    def _stop_listener(self) -> None:
        listener = self.listener
        self.listener = None
        if listener is not None:
            listener.stop()
```

Do not add chord parsing or change `_key_name()` semantics.

- [ ] **Step 4: Run focused hotkey tests**

```powershell
python -m pytest tests/ui/test_app_smoke.py -k "hotkey" -q
python -m ruff check flow_runner/ui/hotkeys.py tests/ui/test_app_smoke.py
```

Expected: PASS.

- [ ] **Step 5: Commit Task 1**

```powershell
git add flow_runner/ui/hotkeys.py tests/ui/test_app_smoke.py
git diff --cached --name-only
git commit -m "feat: reconfigure hotkeys at runtime"
```

### Task 2: Filter Effective Control Keys Before Recording

**Files:**

- Modify: `flow_runner/infrastructure/input/recording.py`
- Modify: `tests/integration/test_actions.py`

- [ ] **Step 1: Add failing ingestion-filter tests**

Add tests using real `RecordingRecorder` callbacks:

```python
def test_recording_recorder_excludes_configured_control_key_pairs(tmp_path):
    callbacks = {}

    class Listener:
        def start(self):
            pass

        def stop(self):
            pass

    recorder = RecordingRecorder(
        listener_factory=lambda **provided: callbacks.update(provided) or Listener()
    )
    recorder.set_ignored_keys({"F6", "F10"})
    recorder.start()
    callbacks["on_release"]("f6")
    callbacks["on_press"]("f10")
    callbacks["on_release"]("f10")
    callbacks["on_press"]("a")
    callbacks["on_release"]("a")

    events = recorder.stop(tmp_path / "recording.json")

    assert [(event.kind, event.data["key"]) for event in events] == [
        ("key_press", "a"),
        ("key_release", "a"),
    ]
```

Add a live-update test:

```python
def test_recording_recorder_updates_ignored_keys_during_recording(tmp_path):
    callbacks = {}

    class Listener:
        def start(self):
            pass

        def stop(self):
            pass

    recorder = RecordingRecorder(
        listener_factory=lambda **provided: callbacks.update(provided) or Listener()
    )
    recorder.set_ignored_keys({"F6"})
    recorder.start()
    callbacks["on_press"]("f6")
    recorder.set_ignored_keys({"F10"})
    callbacks["on_press"]("f6")
    callbacks["on_press"]("f10")

    events = recorder.stop(tmp_path / "recording.json")

    assert [event.data["key"] for event in events] == ["f6"]
```

- [ ] **Step 2: Run tests and verify RED**

```powershell
python -m pytest tests/integration/test_actions.py -k "excludes_configured_control or updates_ignored_keys" -q
```

Expected: FAIL because `set_ignored_keys` does not exist and control keys are currently appended.

- [ ] **Step 3: Implement thread-safe pre-append filtering**

Add state in `RecordingRecorder.__init__`:

```python
self._ignored_keys: frozenset[str] = frozenset()
```

Add the update method:

```python
def set_ignored_keys(self, keys: Iterable[object]) -> None:
    normalized = frozenset(
        str(key).strip().upper()
        for key in keys
        if str(key).strip()
    )
    with self._lock:
        self._ignored_keys = normalized
```

Import `Iterable` from `collections.abc`. Extend `_append` so key filtering and event insertion
happen under the same lock:

```python
def _append(
    self,
    kind: str,
    data: dict[str, Any],
    *,
    key_name: str | None = None,
) -> None:
    with self._lock:
        if self.listener is None or self._paused_at is not None:
            return
        if key_name is not None and key_name.strip().upper() in self._ignored_keys:
            return
        ...

def _on_press(self, key: object) -> None:
    name = _input_name(key)
    self._append("key_press", {"key": name}, key_name=name)

def _on_release(self, key: object) -> None:
    name = _input_name(key)
    self._append("key_release", {"key": name}, key_name=name)
```

Do not filter mouse events and do not perform post-save JSON cleanup.

- [ ] **Step 4: Run recorder and playback regression tests**

```powershell
python -m pytest tests/integration/test_actions.py -k "recording_recorder or recording_player" -q
python -m ruff check flow_runner/infrastructure/input/recording.py tests/integration/test_actions.py
```

Expected: PASS.

- [ ] **Step 5: Commit Task 2**

```powershell
git add flow_runner/infrastructure/input/recording.py tests/integration/test_actions.py
git diff --cached --name-only
git commit -m "fix: exclude control hotkeys from recordings"
```

### Task 3: Dedicated Recording Pause UI and Settings Surface

**Files:**

- Modify: `flow_runner/ui/dialogs/settings_dialog.py`
- Modify: `flow_runner/ui/icons.py`
- Modify: `flow_runner/ui/main_window.py`
- Modify: `tests/ui/test_app_smoke.py`
- Modify: `tests/ui/test_icons.py`
- Modify: `tests/ui/test_main_window.py`

- [ ] **Step 1: Add failing settings and action-state tests**

Extend SettingsDialog coverage:

```python
def test_settings_dialog_round_trips_record_pause_hotkey(qtbot):
    dialog = SettingsDialog(
        HotkeyConfig(record_pause="F10"),
        {"hotkeys": {"record_pause": "F10"}},
    )
    qtbot.addWidget(dialog)
    assert dialog.entries["record_pause"].text() == "F10"
    assert dialog.project_settings()["hotkeys"]["record_pause"] == "F10"
```

Add MainWindow action tests:

```python
def test_recording_pause_action_has_independent_states(qtbot):
    window = MainWindow(sample_project())
    qtbot.addWidget(window)
    assert not window.record_pause_action.isEnabled()
    assert window.record_pause_action.text() == "暂停录制"

    window.set_recording_state(True, paused=False)
    assert window.record_pause_action.isEnabled()
    pause_icon = window.record_pause_action.icon().cacheKey()

    window.set_recording_state(True, paused=True)
    assert window.record_pause_action.text() == "继续录制"
    assert window.record_pause_action.icon().cacheKey() != pause_icon

    window.set_recording_state(False)
    assert not window.record_pause_action.isEnabled()
```

Add signal tests proving toolbar and the new request signal converge on the same action. Update the
responsive-control expected action set and `ACTION_ICON_NAMES` assertions to include
`pauseRecordingAction`:

```python
def test_recording_pause_action_emits_request(qtbot):
    window = MainWindow(sample_project())
    qtbot.addWidget(window)
    window.set_recording_state(True)

    with qtbot.waitSignal(window.recordPauseRequested):
        window.record_pause_action.trigger()


def test_settings_action_emits_changed_hotkey_config(qtbot):
    updated = {
        "hotkeys": {
            "start": "F11",
            "stop": "F12",
            "pause": "F10",
            "record": "F8",
            "record_pause": "F9",
        }
    }
    window = MainWindow(sample_project(), edit_settings=lambda current: updated)
    qtbot.addWidget(window)

    with qtbot.waitSignal(window.hotkeyConfigChanged) as changed:
        window.settings_action.trigger()

    assert changed.args == [HotkeyConfig.model_validate(updated["hotkeys"])]
```

- [ ] **Step 2: Run tests and verify RED**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_main_window.py tests/ui/test_app_smoke.py tests/ui/test_icons.py -k "record_pause or recording_pause_action" -q
```

Expected: FAIL because the field, action, signal, and two-state UI method do not exist.

- [ ] **Step 3: Implement the settings label and independent action**

In `SettingsDialog`, extend the label mapping:

```python
"record_pause": "暂停/继续录制热键",
```

In `MainWindow`, add signals:

```python
recordPauseRequested = Signal()
hotkeyConfigChanged = Signal(object)
```

Create the action beside `record_action`:

```python
self.record_pause_action = QAction("暂停录制", self)
self.record_pause_action.setObjectName("pauseRecordingAction")
self.record_pause_action.setEnabled(False)
self.record_pause_action.triggered.connect(self.recordPauseRequested.emit)
```

Add it to the left runtime controls immediately after `record_action`, add
`"pauseRecordingAction": "pause"` to `ACTION_ICON_NAMES`, and replace the UI state method with:

```python
def set_recording_state(self, recording: bool, *, paused: bool = False) -> None:
    self.record_action.setText("停止录制" if recording else "录制")
    self.record_action.setProperty("status", "recording" if recording else "idle")
    self.record_pause_action.setEnabled(recording)
    self.record_pause_action.setText("继续录制" if recording and paused else "暂停录制")
    self.record_pause_action.setIcon(icon("resume" if recording and paused else "pause"))
```

In `_edit_project_settings`, compare validated old/new hotkeys and emit only when changed. Set the
generic message before the signal so a connected failure handler can replace it:

```python
previous_hotkeys = HotkeyConfig.model_validate(
    self.view_model.project.settings.get("hotkeys", {})
)
updated_hotkeys = HotkeyConfig.model_validate(settings.get("hotkeys", {}))
self.view_model.update_settings(settings)
self.statusBar().showMessage("设置已更新；OCR 引擎将在下次启动时生效")
if updated_hotkeys != previous_hotkeys:
    self.hotkeyConfigChanged.emit(updated_hotkeys)
```

- [ ] **Step 4: Run UI tests**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_main_window.py tests/ui/test_app_smoke.py tests/ui/test_icons.py -q
python -m ruff check flow_runner/ui/dialogs/settings_dialog.py flow_runner/ui/icons.py flow_runner/ui/main_window.py tests/ui/test_main_window.py tests/ui/test_app_smoke.py tests/ui/test_icons.py
```

Expected: PASS.

- [ ] **Step 5: Commit Task 3**

```powershell
git add flow_runner/ui/dialogs/settings_dialog.py flow_runner/ui/icons.py flow_runner/ui/main_window.py tests/ui/test_app_smoke.py tests/ui/test_icons.py tests/ui/test_main_window.py
git diff --cached --name-only
git commit -m "feat: add independent recording pause controls"
```

### Task 4: Application Coordination, Immediate Hotkeys, and State Independence

**Files:**

- Modify: `flow_runner/app.py`
- Modify: `tests/ui/test_app_smoke.py`

- [ ] **Step 1: Add failing end-to-end lifecycle tests**

Add a no-runtime recording-pause test with fake listeners:

```python
def test_recording_pause_button_and_hotkey_work_without_runtime(qtbot, tmp_path):
    hotkey_listeners = []
    callbacks = {}

    class Listener:
        def __init__(self, on_press=None):
            self.on_press = on_press

        def start(self):
            pass

        def stop(self):
            pass

    def hotkey_factory(on_press):
        listener = Listener(on_press)
        hotkey_listeners.append(listener)
        return listener

    composition = create_application(
        [],
        project_path=tmp_path / "project.json",
        hotkey_config=HotkeyConfig(
            start="",
            stop="",
            pause="",
            record="F6",
            record_pause="F10",
        ),
        hotkey_listener_factory=hotkey_factory,
        recording_listener_factory=lambda **provided: callbacks.update(provided) or Listener(),
        recording_path=tmp_path / "latest.json",
    )
    qtbot.addWidget(composition.window)
    composition.start_services()

    hotkey_listeners[0].on_press("f6")
    assert composition.recorder.is_recording
    hotkey_listeners[0].on_press("f10")
    assert composition.recorder.is_paused
    hotkey_listeners[0].on_press("f10")
    assert not composition.recorder.is_paused
    composition.shutdown()
```

Replace the existing `test_application_pause_and_stop_coordinate_active_recording`, whose assertions
encode the old coupling, with this real-runner independence regression:

```python
def test_workflow_and_recording_pause_are_independent(qtbot, tmp_path):
    callbacks = {}

    class Listener:
        def start(self):
            pass

        def stop(self):
            pass

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
    composition = create_application(
        [],
        project_path=project_path,
        recording_listener_factory=lambda **provided: callbacks.update(provided)
        or Listener(),
        recording_path=tmp_path / "latest.json",
    )
    qtbot.addWidget(composition.window)
    composition.window.record_action.trigger()
    with qtbot.waitSignal(composition.runner_bridge.eventReceived, timeout=3000):
        composition.window.start_action.trigger()

    composition.window.pause_action.trigger()
    qtbot.waitUntil(lambda: composition.runner.state is RunnerState.PAUSED)
    qtbot.waitUntil(
        lambda: composition.window.run_view_model.state is RunnerState.PAUSED
    )
    assert composition.recorder.is_recording
    assert not composition.recorder.is_paused

    composition.window.record_pause_action.trigger()
    assert composition.recorder.is_paused
    assert composition.runner.state is RunnerState.PAUSED

    composition.window.pause_action.trigger()
    qtbot.waitUntil(lambda: composition.runner.state is RunnerState.RUNNING)
    assert composition.recorder.is_paused

    composition.window.record_pause_action.trigger()
    assert not composition.recorder.is_paused
    assert composition.runner.state is RunnerState.RUNNING

    with qtbot.waitSignal(composition.runner_bridge.terminated, timeout=3000):
        composition.window.stop_action.trigger()
    composition.shutdown()
```

Add an explicit-stop regression proving a manually paused recording is stopped and saved:

```python
def test_runtime_stop_saves_manually_paused_recording(qtbot, tmp_path):
    callbacks = {}

    class Listener:
        def start(self):
            pass

        def stop(self):
            pass

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
        recording_listener_factory=lambda **provided: callbacks.update(provided)
        or Listener(),
        recording_path=recording_path,
    )
    qtbot.addWidget(composition.window)
    composition.window.record_action.trigger()
    callbacks["on_press"]("a")
    composition.window.record_pause_action.trigger()
    with qtbot.waitSignal(composition.runner_bridge.eventReceived, timeout=3000):
        composition.window.start_action.trigger()

    with qtbot.waitSignal(composition.runner_bridge.terminated, timeout=3000):
        composition.window.stop_action.trigger()

    assert not composition.recorder.is_recording
    assert [event.data["key"] for event in RecordingStore.load(recording_path)] == ["a"]
    composition.shutdown()
```

Add immediate settings reconfiguration with filtering:

```python
def test_saved_hotkey_changes_apply_and_filter_immediately(qtbot, tmp_path):
    hotkey_listeners = []
    recording_callbacks = {}

    class Listener:
        def __init__(self, on_press=None):
            self.on_press = on_press
            self.stopped = False

        def start(self):
            pass

        def stop(self):
            self.stopped = True

    def hotkey_factory(on_press):
        listener = Listener(on_press)
        hotkey_listeners.append(listener)
        return listener

    recording_path = tmp_path / "latest.json"
    composition = create_application(
        [],
        project_path=tmp_path / "project.json",
        hotkey_config=HotkeyConfig(
            start="F11",
            stop="F12",
            pause="F10",
            record="F6",
            record_pause="",
        ),
        hotkey_listener_factory=hotkey_factory,
        recording_listener_factory=lambda **provided: recording_callbacks.update(provided)
        or Listener(),
        recording_path=recording_path,
    )
    qtbot.addWidget(composition.window)
    composition.start_services()
    hotkey_listeners[0].on_press("f6")
    recording_callbacks["on_release"]("f6")

    replacement = HotkeyConfig(
        start="F11",
        stop="F12",
        pause="F10",
        record="F8",
        record_pause="F9",
    )
    composition.window.edit_settings = lambda current: {
        **current,
        "hotkeys": replacement.model_dump(),
    }
    composition.window.settings_action.trigger()

    assert hotkey_listeners[0].stopped
    assert len(hotkey_listeners) == 2
    recording_callbacks["on_press"]("f6")
    recording_callbacks["on_release"]("f6")
    for key in ("f8", "f9", "f10", "f11", "f12"):
        recording_callbacks["on_press"](key)
        recording_callbacks["on_release"](key)

    hotkey_listeners[1].on_press("f9")
    assert composition.recorder.is_paused
    hotkey_listeners[1].on_press("f9")
    assert not composition.recorder.is_paused
    hotkey_listeners[1].on_press("f8")

    events = RecordingStore.load(recording_path)
    assert [(event.kind, event.data["key"]) for event in events] == [
        ("key_press", "f6"),
        ("key_release", "f6"),
    ]
    composition.shutdown()
```

The final assertion proves that the removed old key becomes recordable while all five replacement
control keys remain filtered.

- [ ] **Step 2: Run tests and verify RED**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_app_smoke.py -k "pause_button_and_hotkey or pause_are_independent or hotkey_changes_apply" -q
```

Expected: FAIL because application composition does not wire the new action, still couples runtime
pause to recording, and does not reconfigure services or filters.

- [ ] **Step 3: Implement independent recording coordination**

In `ApplicationComposition`, remove `set_runtime_paused`. Add:

```python
def toggle_recording_pause(self) -> None:
    if not self.recorder.is_recording:
        return
    if self.recorder.is_paused:
        self.recorder.resume()
        self.window.set_recording_state(True, paused=False)
        self.window.statusBar().showMessage("正在录制输入")
    else:
        self.recorder.pause()
        self.window.set_recording_state(True, paused=True)
        self.window.statusBar().showMessage("录制已暂停")

def apply_hotkey_config(self, config: HotkeyConfig) -> None:
    try:
        self.hotkey_service.reconfigure(config)
    except Exception as error:
        self.recorder.set_ignored_keys(self.hotkey_service.control_keys)
        self.window.statusBar().showMessage(f"快捷键更新失败：{error}")
        return
    self.recorder.set_ignored_keys(self.hotkey_service.control_keys)
    self.window.statusBar().showMessage("快捷键已更新")
```

Ensure every start/stop path passes `paused=False` when resetting UI. Stopping an already paused
recorder continues to call `RecordingRecorder.stop()` directly.

- [ ] **Step 4: Wire initial filtering, actions, and settings updates**

After resolving `configured_hotkeys`, initialize filtering:

```python
recorder.set_ignored_keys(configured_hotkeys.enabled_bindings())
```

Add the hotkey action:

```python
"record_pause": window.recordPauseRequested.emit,
```

Connect:

```python
window.recordPauseRequested.connect(lambda: composition.toggle_recording_pause())
window.hotkeyConfigChanged.connect(lambda config: composition.apply_hotkey_config(config))
```

Delete the connection from `runtimePauseChanged` to recorder pause. Keep accepted runtime-stop
coordination unchanged.

- [ ] **Step 5: Run lifecycle and hotkey regression suites**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_app_smoke.py tests/ui/test_main_window.py tests/integration/test_actions.py -q
python -m ruff check flow_runner/app.py tests/ui/test_app_smoke.py
```

Expected: PASS.

- [ ] **Step 6: Commit Task 4**

```powershell
git add flow_runner/app.py tests/ui/test_app_smoke.py
git diff --cached --name-only
git commit -m "feat: coordinate live hotkeys and recording state"
```

### Task 5: Remember Collapsed Flow Groups Locally Per Project

**Files:**

- Create: `flow_runner/ui/flow_tree_preferences.py`
- Create: `tests/ui/test_flow_tree_preferences.py`
- Modify: `flow_runner/ui/panels/flow_tree_panel.py`
- Modify: `flow_runner/ui/main_window.py`
- Modify: `tests/ui/test_main_window.py`

- [ ] **Step 1: Add failing local-preference tests**

Create `tests/ui/test_flow_tree_preferences.py`:

```python
from uuid import uuid4

from PySide6.QtCore import QSettings

from flow_runner.ui.flow_tree_preferences import FlowTreePreferences


def test_flow_tree_preferences_round_trip_and_isolate_projects(tmp_path):
    settings = QSettings(str(tmp_path / "tree.ini"), QSettings.Format.IniFormat)
    preferences = FlowTreePreferences(settings)
    first_project = uuid4()
    second_project = uuid4()
    group_id = uuid4()

    preferences.set_collapsed_groups(first_project, {group_id})
    settings.sync()

    reopened = FlowTreePreferences(
        QSettings(str(tmp_path / "tree.ini"), QSettings.Format.IniFormat)
    )
    assert reopened.collapsed_groups(first_project) == frozenset({group_id})
    assert reopened.collapsed_groups(second_project) == frozenset()


def test_flow_tree_preferences_ignore_malformed_group_ids(tmp_path):
    project_id = uuid4()
    settings = QSettings(str(tmp_path / "tree.ini"), QSettings.Format.IniFormat)
    settings.setValue(
        f"flow_tree/{project_id}/collapsed_groups",
        ["bad-id", str(uuid4())],
    )
    assert len(FlowTreePreferences(settings).collapsed_groups(project_id)) == 1
```

Add MainWindow integration tests with injected preferences:

```python
def test_flow_group_collapse_is_local_and_does_not_dirty_project(qtbot, tmp_path):
    settings = QSettings(str(tmp_path / "tree.ini"), QSettings.Format.IniFormat)
    preferences = FlowTreePreferences(settings)
    project = sample_project()
    window = MainWindow(project, flow_tree_preferences=preferences)
    qtbot.addWidget(window)

    first_group = window.flow_tree.tree.topLevelItem(0)
    first_group.setExpanded(False)
    settings.sync()

    assert not window.view_model.dirty
    reopened = MainWindow(
        project,
        flow_tree_preferences=FlowTreePreferences(
            QSettings(str(tmp_path / "tree.ini"), QSettings.Format.IniFormat)
        ),
    )
    qtbot.addWidget(reopened)
    assert not reopened.flow_tree.tree.topLevelItem(0).isExpanded()


def test_flow_group_collapse_survives_refresh_and_new_groups_default_open(
    qtbot, tmp_path
):
    preferences = FlowTreePreferences(
        QSettings(str(tmp_path / "tree.ini"), QSettings.Format.IniFormat)
    )
    project = sample_project()
    window = MainWindow(project, flow_tree_preferences=preferences)
    qtbot.addWidget(window)
    window.flow_tree.tree.topLevelItem(0).setExpanded(False)

    group_id = window.view_model.project.groups[0].id
    window.view_model.rename_group(group_id, "已重命名")
    assert not window.flow_tree.tree.topLevelItem(0).isExpanded()

    window.view_model.add_group(FlowGroup(name="新增组"))
    newest = window.flow_tree.tree.topLevelItem(
        window.flow_tree.tree.topLevelItemCount() - 1
    )
    assert newest.isExpanded()
```

- [ ] **Step 2: Run tests and verify RED**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_flow_tree_preferences.py tests/ui/test_main_window.py -k "flow_tree or group_expansion" -q
```

Expected: collection failure because `FlowTreePreferences` does not exist, followed by missing
expansion restoration behavior.

- [ ] **Step 3: Implement the QSettings wrapper**

Create `flow_runner/ui/flow_tree_preferences.py`:

```python
from collections.abc import Iterable
from uuid import UUID

from PySide6.QtCore import QSettings


class FlowTreePreferences:
    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings if settings is not None else QSettings()

    def collapsed_groups(self, project_id: UUID) -> frozenset[UUID]:
        raw = self._settings.value(self._key(project_id), [])
        values = raw if isinstance(raw, (list, tuple)) else [raw]
        collapsed = set()
        for value in values:
            try:
                collapsed.add(UUID(str(value)))
            except (TypeError, ValueError):
                continue
        return frozenset(collapsed)

    def set_collapsed_groups(
        self, project_id: UUID, group_ids: Iterable[UUID]
    ) -> None:
        self._settings.setValue(
            self._key(project_id),
            sorted(str(group_id) for group_id in group_ids),
        )

    @staticmethod
    def _key(project_id: UUID) -> str:
        return f"flow_tree/{project_id}/collapsed_groups"
```

- [ ] **Step 4: Add FlowTreePanel expansion API**

In `FlowTreePanel`, add:

```python
groupExpansionChanged = Signal(object, bool)
```

Connect `tree.itemExpanded` and `tree.itemCollapsed`. Emit only for items whose kind is `group` and
whose UUID is valid. Add:

```python
def restore_collapsed_groups(self, collapsed: frozenset[UUID]) -> frozenset[UUID]:
    valid = frozenset(group_id for group_id in collapsed if group_id in self._group_items)
    for group_id, item in self._group_items.items():
        item.setExpanded(group_id not in valid)
    return valid

def collapsed_group_ids(self) -> frozenset[UUID]:
    return frozenset(
        group_id for group_id, item in self._group_items.items() if not item.isExpanded()
    )
```

Use a `_restoring_expansion` guard so programmatic restore does not emit persistence changes.
Leave the parallel root behavior unchanged.

- [ ] **Step 5: Restore and persist through MainWindow**

Add optional constructor injection:

```python
flow_tree_preferences: FlowTreePreferences | None = None,
```

Store the dependency, connect `groupExpansionChanged`, and call a helper after initial construction
and immediately after every `flow_tree.set_project(project)`:

```python
def _restore_flow_group_expansion(self) -> None:
    project_id = self.view_model.project.id
    stored = self.flow_tree_preferences.collapsed_groups(project_id)
    valid = self.flow_tree.restore_collapsed_groups(stored)
    if valid != stored:
        self.flow_tree_preferences.set_collapsed_groups(project_id, valid)

def _flow_group_expansion_changed(self, _group_id: UUID, _expanded: bool) -> None:
    self.flow_tree_preferences.set_collapsed_groups(
        self.view_model.project.id,
        self.flow_tree.collapsed_group_ids(),
    )
```

Do not call `ProjectViewModel.update_settings()` and do not add this state to project JSON.

- [ ] **Step 6: Run flow-tree and MainWindow tests**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_flow_tree_preferences.py tests/ui/test_main_window.py tests/ui/test_simple_shell.py -q
python -m ruff check flow_runner/ui/flow_tree_preferences.py flow_runner/ui/panels/flow_tree_panel.py flow_runner/ui/main_window.py tests/ui/test_flow_tree_preferences.py tests/ui/test_main_window.py
```

Expected: PASS.

- [ ] **Step 7: Commit Task 5**

```powershell
git add flow_runner/ui/flow_tree_preferences.py flow_runner/ui/panels/flow_tree_panel.py flow_runner/ui/main_window.py tests/ui/test_flow_tree_preferences.py tests/ui/test_main_window.py
git diff --cached --name-only
git commit -m "feat: remember flow group expansion locally"
```

### Task 6: Documentation, Complete Verification, and Manual Acceptance

**Files:**

- Modify: `README.md`

- [ ] **Step 1: Update user documentation**

Update the runtime-control documentation to state:

- `暂停录制` is independent from workflow pause and works without a running workflow;
- `record_pause` defaults to disabled and is configured in Settings;
- all five effective control hotkeys are excluded from recordings;
- saved hotkey changes take effect immediately;
- workflow stop saves active or paused recording, while natural completion leaves it active;
- flow-group expansion state is local per project and does not dirty project JSON;
- remove the old statement that F8 automatically freezes independent recording timestamps.

- [ ] **Step 2: Run focused regression suites**

```powershell
python -m ruff format flow_runner tests
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/integration/test_actions.py tests/ui/test_app_smoke.py tests/ui/test_icons.py tests/ui/test_main_window.py tests/ui/test_flow_tree_preferences.py tests/ui/test_simple_shell.py -q
```

Expected: PASS.

- [ ] **Step 3: Run the complete global-Python quality gate**

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

Expected: every command exits 0. Report the actual pytest count in the handoff; do not hard-code it
in README.

- [ ] **Step 4: Perform final safety review**

```powershell
git status --short
git diff --check
git diff --stat
git diff -- data/project.json
git diff --cached --name-only
```

Expected: `data/project.json` remains modified only by the user and is absent from the staged set.

- [ ] **Step 5: Commit documentation**

```powershell
git add README.md
git diff --cached --name-only
git commit -m "docs: describe independent recording controls"
```

- [ ] **Step 6: Run manual Windows acceptance**

Launch with global Python:

```powershell
python -m flow_runner.app
```

Verify:

1. start recording without a workflow and pause/resume it by button;
2. configure a recording-pause key and verify it works immediately;
3. workflow pause does not pause recording;
4. recording pause does not pause workflow;
5. explicit workflow stop saves a paused recording;
6. change hotkeys during recording and confirm the new listener/filter take effect immediately;
7. confirm none of the five current control keys appear in `data/recordings/latest.json`;
8. collapse groups in two projects and confirm local, independent restoration after refresh/restart.

Do not claim these checks passed until they are observed by the user or Computer Use.

---

## Completion Criteria

- All six task commits exist and contain only scoped files.
- Workflow and recording pause states are independent.
- The dedicated recording-pause button and optional hotkey work without a runtime.
- Every effective control hotkey is filtered at recorder ingestion, including after live changes.
- Flow-group collapse state restores locally per project without dirtying project JSON.
- The full global-Python quality gate passes.
- `data/project.json` is never staged or modified by implementation work.

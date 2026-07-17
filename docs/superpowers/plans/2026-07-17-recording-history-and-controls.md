# Recording History and Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Save every completed recording to both timestamped history and `latest.json`, add an icon-only recordings-directory control, and reorder and rename the workflow movement controls.

**Architecture:** `flow_runner.infrastructure.paths` selects collision-free timestamped destinations, while `RecordingRecorder` writes one validated event snapshot to all requested destinations. `MainWindow` owns presentation and emits an open-directory intent; `ApplicationComposition` owns the active directory, desktop-service call, and shared stop-and-save workflow.

**Tech Stack:** Python 3.12, PySide6, Pydantic, pytest, pytest-qt, Ruff, mypy

---

## File Map

- Modify `flow_runner/infrastructure/paths.py`: generate collision-free timestamped recording paths.
- Modify `flow_runner/infrastructure/input/recording.py`: save one completed recording to a primary and additional destination.
- Modify `flow_runner/ui/main_window.py`: add the directory action, icon-only button, signal, label change, and control reordering.
- Modify `flow_runner/ui/icons.py`: register the open-folder action icon.
- Create `flow_runner/resources/icons/folder-open.svg`: packaged open-folder icon.
- Modify `flow_runner/app.py`: centralize dual-save stops and open the active recordings directory.
- Modify focused unit, integration, and UI tests named below.
- Modify `README.md`: document timestamped history, stable latest file, and directory control.

Do not modify `data/project.json`, the two untracked screenshots, or other user-owned worktree changes. Do not commit unless the user explicitly requests a commit.

### Task 1: Timestamped Recording Destinations

**Files:**
- Modify: `flow_runner/infrastructure/paths.py`
- Modify: `tests/unit/infrastructure/test_application_paths.py`

- [ ] **Step 1: Write failing timestamp and collision tests**

Add the imports and test below:

```python
from datetime import datetime

from flow_runner.infrastructure.paths import (
    ApplicationPaths,
    timestamped_recording_file,
)


def test_timestamped_recording_file_uses_local_save_time_and_avoids_collisions(tmp_path):
    saved_at = datetime(2026, 7, 17, 8, 33, 14)

    first = timestamped_recording_file(tmp_path, saved_at)
    first.touch()
    second = timestamped_recording_file(tmp_path, saved_at)
    second.touch()
    third = timestamped_recording_file(tmp_path, saved_at)

    assert first == tmp_path / "recording_20260717_083314.json"
    assert second == tmp_path / "recording_20260717_083314_2.json"
    assert third == tmp_path / "recording_20260717_083314_3.json"
```

- [ ] **Step 2: Run the focused test and verify the expected failure**

Run:

```powershell
python -m pytest tests/unit/infrastructure/test_application_paths.py -q
```

Expected: collection fails because `timestamped_recording_file` does not exist.

- [ ] **Step 3: Implement collision-free timestamp path selection**

Add to `flow_runner/infrastructure/paths.py`:

```python
from datetime import datetime


def timestamped_recording_file(directory: Path, saved_at: datetime) -> Path:
    stem = f"recording_{saved_at:%Y%m%d_%H%M%S}"
    candidate = directory / f"{stem}.json"
    suffix = 2
    while candidate.exists():
        candidate = directory / f"{stem}_{suffix}.json"
        suffix += 1
    return candidate
```

Keep `ApplicationPaths.latest_recording_file` unchanged so stable references continue to resolve to
`recordings/latest.json`.

- [ ] **Step 4: Run the path tests**

Run:

```powershell
python -m pytest tests/unit/infrastructure/test_application_paths.py -q
```

Expected: all tests in the file pass.

- [ ] **Step 5: Review the focused diff**

Run:

```powershell
git diff -- flow_runner/infrastructure/paths.py tests/unit/infrastructure/test_application_paths.py
```

Expected: only the timestamp helper and its focused test are present. Do not commit unless requested.

### Task 2: Dual-Destination Recording Save

**Files:**
- Modify: `flow_runner/infrastructure/input/recording.py`
- Modify: `tests/integration/test_actions.py`

- [ ] **Step 1: Write a failing identical-content test**

Extend the existing recorder capture test or add this focused test using the local fake listener
pattern already present in `tests/integration/test_actions.py`:

```python
def test_recording_recorder_saves_identical_primary_and_latest_files(tmp_path):
    callbacks = {}

    class Listener:
        def start(self):
            pass

        def stop(self):
            pass

    recorder = RecordingRecorder(
        listener_factory=lambda **provided: callbacks.update(provided) or Listener(),
        clock=iter([10.0, 10.1]).__next__,
    )
    archive = tmp_path / "recording_20260717_083314.json"
    latest = tmp_path / "latest.json"

    recorder.start()
    callbacks["on_move"](8, 9)
    events = recorder.stop(archive, additional_paths=(latest,))

    assert RecordingStore.load(archive) == events
    assert RecordingStore.load(latest) == events
    assert archive.read_bytes() == latest.read_bytes()
```

- [ ] **Step 2: Run the focused test and verify the expected failure**

Run:

```powershell
python -m pytest tests/integration/test_actions.py::test_recording_recorder_saves_identical_primary_and_latest_files -q
```

Expected: failure because `RecordingRecorder.stop()` does not accept `additional_paths`.

- [ ] **Step 3: Implement multi-destination saving from one event snapshot**

Update the method signature and save loop:

```python
def stop(
    self,
    path: Path,
    *,
    additional_paths: Iterable[Path] = (),
) -> list[RecordedEvent]:
    listener = self.listener
    if listener is None:
        return []
    listener.stop()
    with self._lock:
        self.listener = None
        events = list(self.events)
    for destination in (path, *additional_paths):
        RecordingStore.save(destination, events)
    return events
```

Reuse the module's existing `Iterable` import. Keep exception propagation unchanged so callers only
report success after all destinations are written.

- [ ] **Step 4: Run all recording integration tests**

Run:

```powershell
python -m pytest tests/integration/test_actions.py -q
```

Expected: all integration tests pass, including existing save-failure and paused-recording cases.

- [ ] **Step 5: Review the focused diff**

Run:

```powershell
git diff -- flow_runner/infrastructure/input/recording.py tests/integration/test_actions.py
```

Expected: one backward-compatible optional argument and one regression test. Do not commit unless requested.

### Task 3: Main-Window Controls and Workflow Action Order

**Files:**
- Modify: `flow_runner/ui/main_window.py`
- Modify: `flow_runner/ui/icons.py`
- Create: `flow_runner/resources/icons/folder-open.svg`
- Modify: `tests/ui/test_main_window.py`
- Modify: `tests/ui/test_icons.py`

- [ ] **Step 1: Write failing action, signal, style, label, and order tests**

Update `test_main_window_places_actions_in_responsive_column_controls` to include
`window.open_recording_directory_action`, then add:

```python
def test_recording_directory_action_is_icon_only_and_follows_record_pause(qtbot):
    window = MainWindow(sample_project())
    qtbot.addWidget(window)
    buttons = window.flow_controls.findChildren(QToolButton)
    actions = [button.defaultAction() for button in buttons]
    directory_button = next(
        button
        for button in buttons
        if button.defaultAction() is window.open_recording_directory_action
    )

    assert actions.index(window.open_recording_directory_action) == (
        actions.index(window.record_pause_action) + 1
    )
    assert directory_button.toolButtonStyle() is Qt.ToolButtonStyle.ToolButtonIconOnly
    assert window.open_recording_directory_action.toolTip() == "打开录制目录"


def test_recording_directory_action_emits_request(qtbot):
    window = MainWindow(sample_project())
    qtbot.addWidget(window)

    with qtbot.waitSignal(window.recordingDirectoryRequested):
        window.open_recording_directory_action.trigger()


def test_workflow_movement_controls_use_requested_order_and_label(qtbot):
    window = MainWindow(sample_project())
    qtbot.addWidget(window)
    actions = [
        button.defaultAction()
        for button in window.flow_controls.findChildren(QToolButton)
    ]
    movement_actions = [
        action
        for action in actions
        if action
        in {
            window.move_workflow_up_action,
            window.move_workflow_group_action,
            window.move_workflow_down_action,
        }
    ]

    assert [action.text() for action in movement_actions] == [
        "流程上移",
        "移动组",
        "流程下移",
    ]
```

In `tests/ui/test_icons.py`, add the mapping assertion and exempt only the new button from the
existing text-beside-icon assertion:

```python
assert ACTION_ICON_NAMES["openRecordingDirectoryAction"] == "folder-open"

assert all(
    button.toolButtonStyle()
    is (
        Qt.ToolButtonStyle.ToolButtonIconOnly
        if button.defaultAction() is window.open_recording_directory_action
        else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
    )
    for button in buttons
    if button.defaultAction() in actions.values()
)
```

- [ ] **Step 2: Run the focused UI tests and verify the expected failures**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/ui/test_main_window.py tests/ui/test_icons.py -q
```

Expected: failures because the new action, signal, icon, label, and order are absent.

- [ ] **Step 3: Add the packaged open-folder icon**

Create `flow_runner/resources/icons/folder-open.svg` using the same high-contrast packaged SVG style:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
  <path fill="none" stroke="#e7eaf4" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M3 18V5a2 2 0 0 1 2-2h4l2 3h7a2 2 0 0 1 2 2v2"/>
  <path fill="none" stroke="#e7eaf4" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" d="M3 18a2 2 0 0 0 2 2h13a2 2 0 0 0 1.94-1.5l1.54-6A2 2 0 0 0 19.54 10H8.24a2 2 0 0 0-1.79 1.11z"/>
</svg>
```

Register it in `ACTION_ICON_NAMES`:

```python
"openRecordingDirectoryAction": "folder-open",
```

- [ ] **Step 4: Add the main-window signal and actions**

In `MainWindow`, add:

```python
recordingDirectoryRequested = Signal()
```

Construct and connect the action after `record_pause_action`:

```python
self.open_recording_directory_action = QAction("打开录制目录", self)
self.open_recording_directory_action.setObjectName("openRecordingDirectoryAction")
self.open_recording_directory_action.setToolTip("打开录制目录")
self.open_recording_directory_action.triggered.connect(
    self.recordingDirectoryRequested.emit
)
```

Change the existing group action text:

```python
self.move_workflow_group_action = QAction("移动组", self)
```

In `_build_workspace_columns`, add the directory action immediately after the record-pause action,
capture its button, and make only that button icon-only:

```python
for action in (
    self.start_action,
    self.pause_action,
    self.stop_action,
    self.record_action,
    self.record_pause_action,
):
    runtime.add_action(action)
directory_button = runtime.add_action(self.open_recording_directory_action)
directory_button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
```

Set the workflow action tuple to:

```python
self.move_workflow_up_action,
self.move_workflow_group_action,
self.move_workflow_down_action,
```

- [ ] **Step 5: Run the focused UI tests**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/ui/test_main_window.py tests/ui/test_icons.py -q
```

Expected: both files pass.

- [ ] **Step 6: Review the focused diff**

Run:

```powershell
git diff -- flow_runner/ui/main_window.py flow_runner/ui/icons.py flow_runner/resources/icons/folder-open.svg tests/ui/test_main_window.py tests/ui/test_icons.py
```

Expected: the new icon-only action and requested action order/text only. Do not commit unless requested.

### Task 4: Application Wiring for Dual Save and Directory Opening

**Files:**
- Modify: `flow_runner/app.py`
- Modify: `tests/ui/test_app_smoke.py`

- [ ] **Step 1: Write failing application-level dual-save tests**

Replace the existing hotkey save test with this complete deterministic version:

```python
from datetime import datetime


def test_record_hotkey_saves_timestamped_history_and_latest_recording(qtbot, tmp_path):
    hotkey_listeners = []
    recording_callbacks = {}

    class Listener:
        def __init__(self, on_press=None):
            self.on_press = on_press
            self.started = False
            self.stopped = False

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

    def hotkey_factory(on_press):
        listener = Listener(on_press)
        hotkey_listeners.append(listener)
        return listener

    recording_listener = Listener()

    def recording_factory(**callbacks):
        recording_callbacks.update(callbacks)
        return recording_listener

    latest = tmp_path / "latest.json"
    composition = create_application(
        [],
        project_path=tmp_path / "project.json",
        hotkey_config=HotkeyConfig(start="", stop="", pause="", record="F9"),
        hotkey_listener_factory=hotkey_factory,
        recording_listener_factory=recording_factory,
        recording_path=latest,
        recording_clock=lambda: datetime(2026, 7, 17, 8, 33, 14),
    )
    qtbot.addWidget(composition.window)
    composition.start_services()

    hotkey_listeners[0].on_press("f9")
    recording_callbacks["on_move"](8, 9)
    hotkey_listeners[0].on_press("f9")

    archive = tmp_path / "recording_20260717_083314.json"
    assert recording_listener.started and recording_listener.stopped
    assert RecordingStore.load(archive) == RecordingStore.load(latest)
    assert archive.read_bytes() == latest.read_bytes()
    composition.shutdown()
```

Add this shutdown-path test:

```python
def test_shutdown_saves_timestamped_history_and_latest_recording(qtbot, tmp_path):
    callbacks = {}

    class Listener:
        def start(self):
            pass

        def stop(self):
            pass

    latest = tmp_path / "latest.json"
    composition = create_application(
        [],
        project_path=tmp_path / "project.json",
        recording_listener_factory=lambda **provided: (
            callbacks.update(provided) or Listener()
        ),
        recording_path=latest,
        recording_clock=lambda: datetime(2026, 7, 17, 8, 33, 15),
    )
    qtbot.addWidget(composition.window)
    composition.window.record_action.trigger()
    callbacks["on_press"]("a")

    composition.shutdown()

    archive = tmp_path / "recording_20260717_083315.json"
    assert RecordingStore.load(archive) == RecordingStore.load(latest)
```

Replace `test_runtime_stop_saves_manually_paused_recording` with the deterministic version below so
the third stop path is covered:

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
    latest = tmp_path / "latest.json"
    composition = create_application(
        [],
        project_path=project_path,
        recording_listener_factory=lambda **provided: (
            callbacks.update(provided) or Listener()
        ),
        recording_path=latest,
        recording_clock=lambda: datetime(2026, 7, 17, 8, 33, 16),
    )
    qtbot.addWidget(composition.window)
    composition.window.record_action.trigger()
    callbacks["on_press"]("a")
    composition.window.record_pause_action.trigger()
    with qtbot.waitSignal(composition.runner_bridge.eventReceived, timeout=3000):
        composition.window.start_action.trigger()

    with qtbot.waitSignal(composition.runner_bridge.terminated, timeout=3000):
        composition.window.stop_action.trigger()

    archive = tmp_path / "recording_20260717_083316.json"
    assert not composition.recorder.is_recording
    assert [event.data["key"] for event in RecordingStore.load(latest)] == ["a"]
    assert RecordingStore.load(archive) == RecordingStore.load(latest)
    composition.shutdown()
```

- [ ] **Step 2: Write failing directory opener tests**

Add:

```python
def test_recording_directory_action_creates_and_opens_active_directory(qtbot, tmp_path):
    opened = []
    project_path = tmp_path / "project.json"
    composition = create_application(
        [],
        project_path=project_path,
        directory_opener=lambda path: opened.append(path) or True,
    )
    qtbot.addWidget(composition.window)

    composition.window.open_recording_directory_action.trigger()

    expected = tmp_path / "recordings"
    assert expected.is_dir()
    assert opened == [expected]
    composition.shutdown()


def test_recording_directory_action_reports_open_failure(qtbot, tmp_path):
    composition = create_application(
        [],
        project_path=tmp_path / "project.json",
        directory_opener=lambda _path: False,
    )
    qtbot.addWidget(composition.window)

    composition.window.open_recording_directory_action.trigger()

    assert "无法打开录制目录" in composition.window.statusBar().currentMessage()
    composition.shutdown()
```

- [ ] **Step 3: Run the focused smoke tests and verify the expected failures**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/ui/test_app_smoke.py -q
```

Expected: failures because the clock/opener injection and centralized dual-save workflow do not yet exist.

- [ ] **Step 4: Add application dependencies and composition fields**

In `flow_runner/app.py`, import `QUrl`, `QDesktopServices`, and
`timestamped_recording_file`. Extend `ApplicationComposition` with:

```python
recording_archive_path_factory: Callable[[], Path]
recording_directory: Path
directory_opener: Callable[[Path], bool]
```

Add the shared save method:

```python
def _stop_and_save_recording(self) -> list[RecordedEvent]:
    return self.recorder.stop(
        self.recording_archive_path_factory(),
        additional_paths=(self.recording_path,),
    )
```

Replace all three direct `self.recorder.stop(self.recording_path)` calls in `shutdown`,
`stop_recording_after_runtime_stop`, and `toggle_recording` with this method.

- [ ] **Step 5: Implement directory opening and wire the new signal**

Add to `ApplicationComposition`:

```python
def open_recording_directory(self) -> None:
    try:
        self.recording_directory.mkdir(parents=True, exist_ok=True)
        opened = self.directory_opener(self.recording_directory)
    except Exception as error:
        self.window.statusBar().showMessage(f"无法打开录制目录：{error}")
        return
    if not opened:
        self.window.statusBar().showMessage(
            f"无法打开录制目录：{self.recording_directory}"
        )
```

Add the default desktop adapter:

```python
def _open_local_directory(path: Path) -> bool:
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))
```

Extend `create_application` with optional deterministic dependencies:

```python
recording_clock: Callable[[], datetime] | None = None,
directory_opener: Callable[[Path], bool] | None = None,
```

Before constructing the composition, calculate:

```python
latest_recording_path = recording_path or paths.latest_recording_file
recording_directory = latest_recording_path.parent
wall_clock = recording_clock or datetime.now
```

Pass these fields:

```python
recording_path=latest_recording_path,
recording_archive_path_factory=lambda: timestamped_recording_file(
    recording_directory,
    wall_clock(),
),
recording_directory=recording_directory,
directory_opener=directory_opener or _open_local_directory,
```

Wire the intent after composition construction:

```python
window.recordingDirectoryRequested.connect(composition.open_recording_directory)
```

Import `RecordedEvent` for the helper return annotation.

- [ ] **Step 6: Run all application smoke tests**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/ui/test_app_smoke.py -q
```

Expected: all application smoke tests pass, including dual-save, shutdown, runtime stop, save
failure, and directory opening.

- [ ] **Step 7: Review the focused diff**

Run:

```powershell
git diff -- flow_runner/app.py tests/ui/test_app_smoke.py
```

Expected: shared save routing and directory opening only. Do not commit unless requested.

### Task 5: Documentation and Full Verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the recording behavior documentation**

Replace the existing `latest.json` paragraph with:

```markdown
Each completed recording is preserved under `data/recordings/recording_YYYYMMDD_HHMMSS.json` and
also copied to `data/recordings/latest.json` for stable playback references. A numeric suffix avoids
overwriting a recording saved in the same second. The icon-only folder control beside the recording
pause control opens the active project's recordings directory.
```

- [ ] **Step 2: Run focused recording and UI suites together**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/unit/infrastructure/test_application_paths.py tests/integration/test_actions.py tests/ui/test_main_window.py tests/ui/test_icons.py tests/ui/test_app_smoke.py -q
```

Expected: all selected tests pass with zero failures.

- [ ] **Step 3: Run static and syntax checks**

Run:

```powershell
python -m ruff check flow_runner tests
python -m mypy flow_runner
python -m compileall flow_runner tests
git diff --check
```

Expected: each command exits successfully with no reported errors.

- [ ] **Step 4: Run the full automated suite**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; python -m pytest -q
```

Expected: the complete suite passes with zero failures.

- [ ] **Step 5: Inspect final repository state and diff**

Run:

```powershell
git status --short
git diff --stat
git diff -- flow_runner tests README.md docs/superpowers/specs/2026-07-17-recording-history-and-controls-design.md docs/superpowers/plans/2026-07-17-recording-history-and-controls.md
```

Expected: user-owned `data/project.json` and screenshots remain untouched; only the planned source,
tests, icon, README, design, and plan changes appear. Do not commit unless requested.

- [ ] **Step 6: Perform the real Windows UI check**

Launch Flow Runner normally and verify:

1. The open-folder icon appears immediately after `暂停录制` with no visible text.
2. Clicking it opens the active `recordings` directory.
3. The workflow controls read `流程上移`, `移动组`, `流程下移` in that order.
4. A short recording creates both a timestamped file and byte-identical `latest.json`.

Report this as a manual check if the current environment cannot safely automate Explorer and global
input recording.

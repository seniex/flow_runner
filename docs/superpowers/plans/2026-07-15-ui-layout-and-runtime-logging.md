# UI Layout and Runtime Logging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Project instructions prohibit subagents and automatic commits unless the user explicitly requests them.

**Goal:** Persist the three editor columns, correct compact UI states, and provide readable per-launch normal/debug logs with an accurate wait-action countdown.

**Architecture:** Flatten the top workspace into one three-column splitter and keep pending layout state outside project history until save. Separate runtime event formatting, session-file creation, safe persistence, and Qt countdown rendering; emit only wait start/final events from the engine while a Qt timer updates the visible countdown locally.

**Tech Stack:** Python 3.12, PySide6, Pydantic, pytest, pytest-qt, Ruff, mypy.

**Preservation:** Do not edit or revert the user's current `project.json`, `templates/`, `flowUI.png`, `BGUI.png`, or `project.*.bak.json` files.

**Execution status (2026-07-15):** Implemented and automatically verified; real UI acceptance remains.

---

### Task 1: Persist the Three Column Splitter

**Files:**
- Modify: `flow_runner/ui/main_window.py`
- Modify: `tests/ui/test_simple_shell.py`
- Modify: `tests/ui/test_main_window.py`

- [ ] **Step 1: Write failing layout tests**

Add tests that construct a project with `settings={"ui_layout": {"column_widths": [180, 320, 700]}}`, show the window, process Qt events, and assert:

```python
assert window.workspace_splitter.count() == 3
assert window.workspace_splitter.widget(0) is window.flow_tree
assert window.workspace_splitter.widget(1) is window.step_list
assert window.workspace_splitter.widget(2) is window.property_panel
assert _same_proportions(window.workspace_splitter.sizes(), [180, 320, 700])
```

Add a save test that calls `setSizes([210, 410, 810])`, emits `splitterMoved`, asserts no project history entry is created before save, triggers Save, and verifies the saved candidate contains exactly three positive `column_widths`. Add invalid-setting fallback and Undo-restores-saved-width tests.

- [ ] **Step 2: Verify RED**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest -q tests\ui\test_simple_shell.py tests\ui\test_main_window.py -k "splitter or column_width"
```

Expected: FAIL because splitters are local/nested and layout state is not persisted.

- [ ] **Step 3: Implement pending layout state**

Flatten the layout and expose splitters:

```python
self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal)
self.workspace_splitter.addWidget(self.flow_tree)
self.workspace_splitter.addWidget(self.step_list)
self.workspace_splitter.addWidget(self.property_panel)
self.content_splitter = QSplitter(Qt.Orientation.Vertical)
self.content_splitter.addWidget(self.workspace_splitter)
self.content_splitter.addWidget(self.runtime_log)
```

Add `_saved_column_widths`, `_pending_column_widths`, `_layout_dirty`, `_restore_column_widths()`, `_column_widths_from_settings()`, and `_capture_layout_settings()`. `splitterMoved` records current sizes and refreshes Save/window-modified state without calling `ProjectViewModel.update_settings`.

Before `_save_project()` calls the persistence callback, merge pending widths once:

```python
settings = dict(self.view_model.project.settings)
settings["ui_layout"] = {**dict(settings.get("ui_layout", {})), "column_widths": widths}
self.view_model.update_settings(settings)
```

Include `_layout_dirty` in save, close, and undo decisions. Initial restore and undo restore must block splitter signals.

- [ ] **Step 4: Verify GREEN**

Run the focused command from Step 2 and then:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest -q tests\ui\test_main_window.py tests\ui\test_simple_shell.py
```

Expected: all tests pass.

### Task 2: Correct Card Visibility and Toolbar Feedback

**Files:**
- Modify: `flow_runner/ui/panels/step_list_panel.py`
- Modify: `flow_runner/resources/styles/base.qss`
- Modify: `tests/ui/test_simple_shell.py`
- Modify: `tests/ui/test_theme_manager.py`

- [ ] **Step 1: Write failing card and QSS tests**

Assert collapsed and expanded card states:

```python
assert item.text() == ""
assert card.title_label.isVisible()
assert card.body.isHidden()
panel.select_step(step.id)
assert card.title_label.isHidden()
assert not card.body.isHidden()
assert card.accessibleName() == step.name
```

Extend the QSS contract test to require `QToolButton`, `QToolButton:hover`, `QToolButton:pressed`, `QToolButton:disabled`, and `QToolButton:checked`.

- [ ] **Step 2: Verify RED**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest -q tests\ui\test_simple_shell.py tests\ui\test_theme_manager.py
```

Expected: card title remains visible when expanded, list item still paints text, and QToolButton selectors are absent.

- [ ] **Step 3: Implement mutually exclusive card content and QSS states**

Create `QListWidgetItem("")`, put the name in accessible/UI roles, enable `Qt.WidgetAttribute.WA_StyledBackground` on the card, and update:

```python
self.title_label.setVisible(not expanded)
self.body.setVisible(expanded)
```

Add QSS-only toolbar states with a visible default border/background, brighter hover border, darker pressed background, muted disabled colors, and accent checked background.

- [ ] **Step 4: Verify GREEN**

Run the command from Step 2. Expected: all pass.

### Task 3: Keep Window Action Controls on One Row

**Files:**
- Modify: `flow_runner/ui/layouts/compact_flow_layout.py`
- Modify: `flow_runner/ui/editors/model_form.py`
- Modify: `flow_runner/ui/editors/action_editor.py`
- Modify: `tests/ui/test_compact_layout.py`
- Modify: `tests/ui/test_step_editors.py`

- [ ] **Step 1: Write failing window-action layout tests**

Build `ModelForm(WindowActionConfig, common_fields=common_fields_for("system.window_action"))`, set a normal property-panel width, and assert operation/title/geometry containers have the same top coordinate. Assert geometry is hidden for `activate` and visible for `move_resize`, while values round-trip.

- [ ] **Step 2: Verify RED**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest -q tests\ui\test_compact_layout.py tests\ui\test_step_editors.py -k "window_action or compact"
```

Expected: geometry wraps and does not follow operation visibility.

- [ ] **Step 3: Implement capability-specific no-wrap layout**

Add a `wrap: bool = True` option to `CompactFlowLayout`; when false, `_do_layout()` never starts a new line. Let `ModelForm` accept `force_single_row` and field visibility dependencies. For `WindowActionConfig`, use `force_single_row=True`, compact tuple-part widths, and connect operation changes so geometry is visible only for `move_resize`.

Do not change model validation or advanced JSON.

- [ ] **Step 4: Verify GREEN**

Run the focused command and the complete `tests\ui\test_step_editors.py` file. Expected: all pass.

### Task 4: Build Runtime Formatting and Per-Launch Log Files

**Files:**
- Create: `flow_runner/infrastructure/logging/formatters.py`
- Create: `flow_runner/infrastructure/logging/session.py`
- Modify: `flow_runner/infrastructure/logging/sinks.py`
- Create: `tests/unit/infrastructure/test_runtime_logging.py`

- [ ] **Step 1: Write failing pure unit tests**

Cover:

```python
formatter = RuntimeEventFormatter(project, debug=False)
assert "组A / 流程一 / 等待加载" in formatter.format(step_event)
assert str(step_event.step_id) not in formatter.format(step_event)

debug = RuntimeEventFormatter(project, debug=True).format(step_event)
assert str(step_event.step_id) in debug
assert "frame-1" in debug
```

Test `session_log_path(log_dir, "项目:名称", started_at, debug=False)` produces `项目_名称_20260715_061530_normal.log`, creates `_2` on collision, and never overwrites. Test empty/special names fall back to `FlowRunner`.

Test `TextEventSink` writes UTF-8 concise lines and `JsonEventSink` writes one complete `RuntimeEvent.model_dump_json()` object per line despite the `.log` extension.

- [ ] **Step 2: Verify RED**

Run:

```powershell
python -m pytest -q tests\unit\infrastructure\test_runtime_logging.py
```

Expected: import failures for the new formatter/session APIs.

- [ ] **Step 3: Implement pure logging components**

Implement:

```python
class RuntimeEventFormatter:
    def __init__(self, project: Project, *, debug: bool = False):
        self.debug = debug
        self.set_project(project)

    def set_project(self, project: Project) -> None:
        self.groups = {workflow.id: group.name for group in project.groups for workflow in group.workflows}
        self.workflows = {workflow.id: workflow.name for group in project.groups for workflow in group.workflows}
        self.steps = {step.id: step.name for group in project.groups for workflow in group.workflows for step in workflow.steps}

    def format(self, event: RuntimeEvent) -> str:
        summary = self._concise_summary(event)
        return f"{summary} | {event.model_dump_json()}" if self.debug else summary

def session_log_path(directory: Path, project_name: str, started_at: datetime, *, debug: bool) -> Path:
    invalid = '<>:"/\\|?*'
    safe = "".join("_" if character in invalid else character for character in project_name)
    safe = safe.strip().rstrip(" .") or "FlowRunner"
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"{safe}_{started_at:%Y%m%d_%H%M%S}_{'debug' if debug else 'normal'}"
    candidate = directory / f"{stem}.log"
    suffix = 2
    while candidate.exists():
        candidate = directory / f"{stem}_{suffix}.log"
        suffix += 1
    candidate.touch(exist_ok=False)
    return candidate

def append_utf8_line(path: Path, text: str) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
        stream.write("\n")
        stream.flush()

class TextEventSink:
    def __init__(self, path: Path, formatter: RuntimeEventFormatter):
        self.path = path
        self.formatter = formatter

    def emit(self, event: RuntimeEvent) -> None:
        append_utf8_line(self.path, self.formatter.format(event))

class JsonEventSink:
    def __init__(self, path: Path):
        self.path = path

    def emit(self, event: RuntimeEvent) -> None:
        append_utf8_line(self.path, event.model_dump_json())
```

Format runner states, step start/finish, wait start/final, route target, result, attempts, elapsed time, and errors in Chinese. Unknown events must retain their raw kind.

- [ ] **Step 4: Verify GREEN**

Run the command from Step 2. Expected: all pass.

### Task 5: Add Debug Setting and Safe Session Sink Wiring

**Files:**
- Modify: `flow_runner/ui/dialogs/settings_dialog.py`
- Modify: `flow_runner/ui/runner_bridge.py`
- Modify: `flow_runner/app.py`
- Modify: `tests/ui/test_app_smoke.py`
- Modify: `tests/ui/test_runner_bridge.py`

- [ ] **Step 1: Write failing integration tests**

Assert SettingsDialog defaults `debug_logging` to false and round-trips true. Create two application compositions in separate temporary project directories and assert each startup creates exactly one matching mode file:

```python
assert len(list(logs.glob("p_*_normal.log"))) == 1
assert not list(logs.glob("p_*_debug.log"))
```

For debug settings, reverse the expectations and emit a RuntimeEvent to verify full JSON fields. Add a bridge test whose persistent sink raises `OSError`; the `failed` signal must receive a message while the runner still completes.

- [ ] **Step 2: Verify RED**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest -q tests\ui\test_app_smoke.py tests\ui\test_runner_bridge.py -k "debug_logging or session_log or sink_failure"
```

Expected: missing setting/session file behavior and persistent sink exception propagation.

- [ ] **Step 3: Implement setting and application wiring**

Add `self.debug_logging_check = QCheckBox("启用调试日志（下次启动生效）")` and include its boolean in `project_settings()`.

At application startup, call `session_log_path()` once. Build only one sink:

```python
debug = bool(project.settings.get("debug_logging", False))
formatter = RuntimeEventFormatter(project, debug=debug)
path = session_log_path(project_path.parent / "logs", project.name, datetime.now(), debug=debug)
sink = JsonEventSink(path) if debug else TextEventSink(path, formatter)
```

Wrap the persistent sink inside RunnerBridge so emit exceptions call `_post("failed", f"日志写入失败：{error}")` and never propagate into Runner.

- [ ] **Step 4: Verify GREEN**

Run the command from Step 2 and then all `test_app_smoke.py` and `test_runner_bridge.py`. Expected: all pass.

### Task 6: Emit Wait Boundaries and Render a One-Second Countdown

**Files:**
- Modify: `flow_runner/engine/workflow_executor.py`
- Modify: `flow_runner/engine/step_executor.py`
- Modify: `flow_runner/engine/runner.py`
- Create: `flow_runner/ui/runtime_log.py`
- Modify: `flow_runner/ui/main_window.py`
- Modify: `tests/unit/engine/test_runner.py`
- Create: `tests/ui/test_runtime_log.py`

- [ ] **Step 1: Write failing engine event tests**

Run a step containing `ActionSpec(capability="system.wait", config={"seconds": 3})` with a fake sleep. Assert ordered events:

```python
assert [event.kind for event in sink.events if event.kind.startswith("action.wait.")] == [
    "action.wait.started",
    "action.wait.finished",
]
assert wait_started.details["seconds"] == 3
assert wait_started.workflow_id == workflow.id
assert wait_started.step_id == step.id
assert wait_started.details["wait_id"] == wait_finished.details["wait_id"]
```

Add cancelled and zero-second cases; add parallel waits and assert unique wait IDs.

- [ ] **Step 2: Verify engine RED**

Run:

```powershell
python -m pytest -q tests\unit\engine\test_runner.py -k "wait_event"
```

Expected: no action.wait events.

- [ ] **Step 3: Implement wait boundary observation**

Add an optional step-identity binder to WorkflowExecutor before each execute call. Let `_GatedStepExecutor` bind Runner's action observer to StepExecutor. Around resolved `system.wait` execution, create one `wait_id`, emit started with actual seconds/action index, then emit finished or cancelled in the corresponding control path. Do not emit per-second events.

- [ ] **Step 4: Write failing Qt countdown tests**

Construct `RuntimeLogController` with a fake clock and manually invoke its one-second tick. Assert one text block changes from `剩余 3 秒` to `剩余 2 秒` without increasing block count. Assert pause freezes, resume continues, finish replaces the same line, cancel says `等待已取消`, and two wait IDs update independently.

- [ ] **Step 5: Verify Qt RED**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest -q tests\ui\test_runtime_log.py
```

Expected: missing RuntimeLogController.

- [ ] **Step 6: Implement RuntimeLogController**

Implement a QObject that owns one `QTimer(interval=1000)`, a mapping keyed by `(task_id, wait_id)`, and QTextBlock references. It formats normal events with RuntimeEventFormatter, updates active wait blocks in place using QTextCursor, freezes elapsed time during PAUSED, and finalizes all waits when the task reaches a terminal state.

MainWindow delegates `eventReceived` to the controller and calls `formatter.set_project()` on project changes. Set a bounded maximum block count and preserve automatic scrolling.

- [ ] **Step 7: Verify GREEN**

Run the engine and Qt focused commands, then:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest -q tests\unit\engine\test_runner.py tests\ui\test_runtime_log.py tests\ui\test_main_window.py
```

Expected: all pass.

### Task 7: Documentation and Full Verification

**Files:**
- Modify: `README.md`
- Modify: `REFACTOR_STATUS.md`
- Modify: `IMPROVEMENT_A_PLAN.md`

- [ ] **Step 1: Update user documentation**

Document saved three-column widths, card state, toolbar feedback, window-action single row, `debug_logging`, per-launch filenames, normal/debug contents, and wait-only countdown behavior. Record that old `runtime.jsonl` files are preserved but no longer appended by the new session logger.

- [ ] **Step 2: Run focused and full verification**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest -q tests\ui
python -m pytest -q
python -m ruff check flow_runner tests scripts
python -m ruff format --check flow_runner tests scripts
python -m mypy flow_runner
python -m compileall -q flow_runner
git diff --check
git status --short
```

Expected: tests and checks pass; status still shows the user's project/template/reference/backup changes untouched.

- [ ] **Step 3: Hand off real UI acceptance**

Ask the user to verify the six items in the design spec. Warn before launching or interacting with the real desktop. Do not alter real configuration beyond the user-approved save and log-file creation behavior.

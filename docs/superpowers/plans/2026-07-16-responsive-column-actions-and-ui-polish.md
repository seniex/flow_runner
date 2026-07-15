# Responsive Column Actions and UI Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the crowded top toolbars with responsive per-column controls, keep all step cards expanded, automate launch-file configuration, present result bindings in Chinese, localize remaining app-owned UI text, and persist the main-window size.

**Architecture:** Keep `MainWindow` as the single owner of `QAction` objects and business callbacks, while new presentation-only column/control widgets bind to those actions. Put launch-file mapping, result-binding labels, and window preferences in small testable modules; keep project JSON and execution schemas unchanged. Preserve existing absolute screen-coordinate behavior and explicitly exclude the native-resolution point/region selector follow-up from this plan.

**Tech Stack:** Python 3.11+, PySide6, Pydantic 2, QSettings, pytest, pytest-qt, Ruff, mypy

---

## Scope Boundary

This plan implements the approved design in
`docs/superpowers/specs/2026-07-16-responsive-column-actions-and-ui-polish-design.md`.
It must not implement the separate follow-up task for mouse coordinate picking, native-resolution
desktop/window overlays, hiding the application during capture, or target-relative fixed mouse
coordinates. Existing screen-derived absolute coordinates remain compatible.

Do not modify, stage, or commit `data/project.json`; it contains user runtime state.

## File Map

**Create:**

- `flow_runner/ui/widgets/responsive_controls.py` — responsive groups, action buttons, and column shell.
- `flow_runner/ui/launch_file_selection.py` — pure `.py`/`.pyw`/`.bat`/executable mapping helpers.
- `flow_runner/ui/result_bindings.py` — internal binding expression to Chinese display-name mapping.
- `flow_runner/ui/window_preferences.py` — validated QSettings access for main-window width and height.
- `tests/ui/test_responsive_controls.py` — width-dependent wrapping tests.
- `tests/ui/test_launch_file_selection.py` — launch mapping and form-autofill tests.
- `tests/ui/test_result_bindings.py` — binding labels, fallback, and editor round-trip tests.
- `tests/ui/test_window_preferences.py` — size persistence and validation tests.
- `tests/ui/test_localized_ui.py` — controlled localization coverage.

**Modify:**

- `flow_runner/ui/widgets/__init__.py` — export new responsive widgets.
- `flow_runner/ui/main_window.py` — build three column shells, remove top toolbars, restore/save size.
- `flow_runner/ui/panels/step_list_panel.py` — always-expanded cards and selection-only highlighting.
- `flow_runner/ui/panels/property_panel.py` — propagate current condition to action/route binding editors.
- `flow_runner/ui/editors/model_form.py` — file-selection signal, launch autofill, Chinese binding selector.
- `flow_runner/ui/editors/action_editor.py` — pass binding options into generated action forms.
- `flow_runner/ui/editors/condition_editor.py` — expose the current condition snapshot for labels.
- `flow_runner/ui/editors/route_editor.py` — use friendly binding selector for result predicates.
- `flow_runner/ui/localization.py` — file-name summaries and complete Chinese label maps.
- `flow_runner/ui/editor_metadata.py` — keep launch fields visible after autofill.
- `flow_runner/app.py` — establish stable QSettings identity.
- `flow_runner/resources/styles/base.qss` — style column shells and responsive control groups.
- `tests/ui/test_main_window.py` — column ownership, no toolbars, wrapping, and size restoration.
- `tests/ui/test_simple_shell.py` — all cards expanded with persistent titles.
- `tests/ui/test_step_editors.py` — action binding options and condition-name propagation.
- `tests/ui/test_model_form_modes.py` — launch form and preference regression coverage.
- `README.md` — document the new control placement and launch convenience.
- `REAL_ENVIRONMENT_CHECKLIST.md` — add real-window responsive and persistence checks.

### Task 1: Responsive Control Widgets

**Files:**
- Create: `flow_runner/ui/widgets/responsive_controls.py`
- Modify: `flow_runner/ui/widgets/__init__.py`
- Test: `tests/ui/test_responsive_controls.py`

- [ ] **Step 1: Write failing geometry and QAction-binding tests**

```python
from PySide6.QtGui import QAction

from flow_runner.ui.widgets.responsive_controls import ColumnContainer, ResponsiveControlArea


def test_responsive_action_group_wraps_and_unwraps_with_width(qtbot):
    area = ResponsiveControlArea()
    qtbot.addWidget(area)
    group = area.add_group("步骤")
    actions = [QAction(text, area) for text in ("新增步骤", "复制步骤", "删除步骤")]
    buttons = [group.add_action(action) for action in actions]

    area.resize(170, 300)
    area.show()
    qtbot.wait(1)
    narrow_rows = {button.geometry().top() for button in buttons}

    area.resize(600, 120)
    qtbot.wait(1)
    wide_rows = {button.geometry().top() for button in buttons}

    assert len(narrow_rows) > len(wide_rows)
    assert len(wide_rows) == 1


def test_responsive_action_button_tracks_qaction_state(qtbot):
    area = ResponsiveControlArea()
    qtbot.addWidget(area)
    action = QAction("保存", area)
    button = area.add_group("项目").add_action(action)
    calls = []
    action.triggered.connect(lambda: calls.append("saved"))

    action.setEnabled(False)
    assert not button.isEnabled()
    action.setEnabled(True)
    button.click()
    assert calls == ["saved"]


def test_column_container_keeps_content_above_controls(qtbot):
    from PySide6.QtWidgets import QLabel

    content = QLabel("内容")
    controls = ResponsiveControlArea()
    column = ColumnContainer(content, controls, object_name="testColumn")
    qtbot.addWidget(column)

    assert column.content is content
    assert column.controls is controls
    assert column.layout().stretch(0) == 1
```

- [ ] **Step 2: Run the new tests and verify the module is missing**

Run: `python -m pytest tests/ui/test_responsive_controls.py -q`

Expected: collection fails with `ModuleNotFoundError: flow_runner.ui.widgets.responsive_controls`.

- [ ] **Step 3: Implement the focused responsive widgets**

```python
# flow_runner/ui/widgets/responsive_controls.py
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QToolButton, QVBoxLayout, QWidget

from flow_runner.ui.layouts import CompactFlowLayout


class ResponsiveControlGroup(QWidget):
    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setProperty("controlGroup", True)
        self.title = QLabel(title)
        self.title.setObjectName("responsiveControlGroupTitle")
        self.body = QWidget()
        self.flow = CompactFlowLayout(self.body, spacing=6)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.title)
        layout.addWidget(self.body)

    def add_action(self, action: QAction) -> QToolButton:
        button = QToolButton(self.body)
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        button.setDefaultAction(action)
        self.flow.addWidget(button)
        return button

    def add_field(self, label: str, editor: QWidget, name: str) -> QWidget:
        return self.flow.addField(label, editor, name)


class ResponsiveControlArea(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("responsiveControlArea")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._layout.setSpacing(6)

    def add_group(self, title: str) -> ResponsiveControlGroup:
        group = ResponsiveControlGroup(title, self)
        self._layout.addWidget(group)
        return group


class ColumnContainer(QWidget):
    def __init__(
        self,
        content: QWidget,
        controls: ResponsiveControlArea,
        *,
        object_name: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName(object_name)
        self.content = content
        self.controls = controls
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(content, 1)
        layout.addWidget(controls)
```

Export all three classes from `flow_runner/ui/widgets/__init__.py`.

- [ ] **Step 4: Run focused tests and lint**

Run: `python -m pytest tests/ui/test_responsive_controls.py -q`

Expected: `3 passed`.

Run: `python -m ruff check flow_runner/ui/widgets tests/ui/test_responsive_controls.py`

Expected: exit code 0.

- [ ] **Step 5: Commit the responsive widget unit**

```powershell
git add flow_runner/ui/widgets/responsive_controls.py flow_runner/ui/widgets/__init__.py tests/ui/test_responsive_controls.py
git commit -m "feat: add responsive column controls"
```

### Task 2: Move Actions Into Their Owning Columns

**Files:**
- Modify: `flow_runner/ui/main_window.py`
- Modify: `flow_runner/resources/styles/base.qss`
- Modify: `tests/ui/test_main_window.py`

- [ ] **Step 1: Replace toolbar assertions with column-ownership tests**

```python
def test_main_window_places_actions_in_responsive_column_controls(qtbot):
    window = MainWindow(sample_project())
    qtbot.addWidget(window)

    assert window.findChild(QToolBar, "runtimeToolbar") is None
    assert window.findChild(QToolBar, "projectToolbar") is None
    assert window.workspace_splitter.widget(0) is window.flow_column
    assert window.workspace_splitter.widget(1) is window.step_column
    assert window.workspace_splitter.widget(2) is window.property_column

    left = {button.defaultAction() for button in window.flow_controls.findChildren(QToolButton)}
    middle = {button.defaultAction() for button in window.step_controls.findChildren(QToolButton)}
    right = {button.defaultAction() for button in window.property_controls.findChildren(QToolButton)}

    assert left == {
        window.start_action, window.pause_action, window.stop_action, window.record_action,
        window.add_group_action, window.copy_group_action, window.add_workflow_action,
        window.copy_workflow_action, window.rename_flow_action, window.move_workflow_up_action,
        window.move_workflow_down_action, window.move_workflow_group_action,
        window.delete_flow_action, window.add_parallel_action, window.edit_parallel_action,
        window.delete_parallel_action,
    }
    assert middle == {
        window.add_template_step_action, window.add_step_action, window.copy_step_action,
        window.remove_step_action, window.move_step_up_action, window.move_step_down_action,
        window.run_step_action, window.preview_action,
    }
    assert right == {
        window.save_action, window.undo_action, window.settings_action,
        window.diagnostics_action,
    }
```

Add a second test that resizes `flow_column` to 220 and 700 pixels, forces layout activation, and
asserts that the left action buttons occupy more distinct `geometry().top()` values at 220 pixels.

- [ ] **Step 2: Run the ownership test and verify it fails against the toolbar layout**

Run: `python -m pytest tests/ui/test_main_window.py::test_main_window_places_actions_in_responsive_column_controls -q`

Expected: FAIL because `flow_column`, `step_column`, and `property_column` do not exist.

- [ ] **Step 3: Build the three control areas after all QActions are created**

Add these helpers to `MainWindow` and call `_build_workspace_columns()` after action creation and
signal connections, replacing the old toolbar population and direct splitter children:

```python
def _build_workspace_columns(self) -> None:
    self.flow_controls = ResponsiveControlArea()
    runtime = self.flow_controls.add_group("运行")
    runtime.add_field("启动组", self.startup_group_combo, "startup_group")
    runtime.add_field("启动流程", self.startup_workflow_combo, "startup_workflow")
    for action in (self.start_action, self.pause_action, self.stop_action, self.record_action):
        runtime.add_action(action)
    flows = self.flow_controls.add_group("组与流程")
    for action in (
        self.add_group_action, self.copy_group_action, self.add_workflow_action,
        self.copy_workflow_action, self.rename_flow_action, self.move_workflow_up_action,
        self.move_workflow_down_action, self.move_workflow_group_action, self.delete_flow_action,
    ):
        flows.add_action(action)
    parallel = self.flow_controls.add_group("并行监控")
    for action in (self.add_parallel_action, self.edit_parallel_action, self.delete_parallel_action):
        parallel.add_action(action)

    self.step_controls = ResponsiveControlArea()
    steps = self.step_controls.add_group("步骤")
    for action in (
        self.add_template_step_action, self.add_step_action, self.copy_step_action,
        self.remove_step_action, self.move_step_up_action, self.move_step_down_action,
        self.run_step_action, self.preview_action,
    ):
        steps.add_action(action)

    self.property_controls = ResponsiveControlArea()
    project = self.property_controls.add_group("项目")
    for action in (
        self.save_action, self.undo_action, self.settings_action, self.diagnostics_action,
    ):
        project.add_action(action)

    self.flow_column = ColumnContainer(
        self.flow_tree, self.flow_controls, object_name="flowColumn"
    )
    self.step_column = ColumnContainer(
        self.step_list, self.step_controls, object_name="stepColumn"
    )
    self.property_column = ColumnContainer(
        self.property_panel, self.property_controls, object_name="propertyColumn"
    )
    self.workspace_splitter.addWidget(self.flow_column)
    self.workspace_splitter.addWidget(self.step_column)
    self.workspace_splitter.addWidget(self.property_column)
```

Remove `QToolBar` construction and `addToolBar()` calls. Keep all existing `QAction` instances,
shortcuts, selectors, signal connections, object names, and state-refresh methods unchanged.

- [ ] **Step 4: Add scoped QSS for the new containers**

```css
#flowColumn,
#stepColumn,
#propertyColumn,
#responsiveControlArea {
    background: #111424;
}

#responsiveControlArea {
    border: 1px solid #2a3150;
}

QWidget[controlGroup="true"] {
    background: transparent;
}

#responsiveControlGroupTitle {
    color: #9da7c7;
    font-weight: 700;
}
```

Retain the existing `QToolButton` states because the new controls use the same widget class.

- [ ] **Step 5: Run main-window behavior tests**

Run: `python -m pytest tests/ui/test_main_window.py -q`

Expected: all tests pass after updating only assertions that referred to the removed toolbars or
direct splitter children. Existing start/pause/stop, save/undo, editing, and close tests must remain.

- [ ] **Step 6: Commit the column integration**

```powershell
git add flow_runner/ui/main_window.py flow_runner/resources/styles/base.qss tests/ui/test_main_window.py
git commit -m "feat: move controls into responsive columns"
```

### Task 3: Keep Every Step Card Expanded

**Files:**
- Modify: `flow_runner/ui/panels/step_list_panel.py`
- Modify: `tests/ui/test_simple_shell.py`

- [ ] **Step 1: Rewrite the card test for the approved invariant**

```python
def test_step_list_keeps_all_cards_expanded_and_titles_visible(qtbot):
    project, first, _second, first_step = _project()
    second_step = AutomationStep(name="第二步")
    first = first.model_copy(update={"steps": [first_step, second_step]})
    panel = StepListPanel()
    qtbot.addWidget(panel)

    panel.set_workflow(first)
    cards = [panel.list.itemWidget(panel.list.item(index)) for index in range(2)]

    assert all(card.is_expanded for card in cards)
    assert all(not card.title_label.isHidden() for card in cards)
    assert all(not card.body.isHidden() for card in cards)
    panel.select_step(second_step.id)
    assert all(card.is_expanded for card in cards)
    assert all(not card.title_label.isHidden() for card in cards)
    assert cards[1].property("selected") is True
    assert cards[0].property("selected") is False
```

- [ ] **Step 2: Run the test and verify current selection-driven expansion fails**

Run: `python -m pytest tests/ui/test_simple_shell.py::test_step_list_keeps_all_cards_expanded_and_titles_visible -q`

Expected: FAIL because unselected cards start collapsed and selected titles are hidden.

- [ ] **Step 3: Separate expansion from selection**

Initialize `StepCardWidget.is_expanded = True`, call `self.body.show()`, and never hide
`title_label`. Replace `set_expanded()` with:

```python
def set_selected(self, selected: bool) -> None:
    self.setProperty("selected", selected)
    self.style().unpolish(self)
    self.style().polish(self)
```

In `StepListPanel.set_workflow()`, update each item size after the expanded card is installed. In
`_on_current_item()`, call `card.set_selected(item is current)` and update the size hint without
changing expansion.

- [ ] **Step 4: Run step-card and main-window selection tests**

Run: `python -m pytest tests/ui/test_simple_shell.py tests/ui/test_main_window.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the card behavior**

```powershell
git add flow_runner/ui/panels/step_list_panel.py tests/ui/test_simple_shell.py
git commit -m "feat: expand all step cards by default"
```

### Task 4: Automate Launch-File Configuration and File Summaries

**Files:**
- Create: `flow_runner/ui/launch_file_selection.py`
- Modify: `flow_runner/ui/editors/model_form.py`
- Modify: `flow_runner/ui/localization.py`
- Test: `tests/ui/test_launch_file_selection.py`
- Modify: `tests/ui/test_step_editors.py`

- [ ] **Step 1: Write pure mapping tests for all approved file types**

```python
def test_launch_selection_maps_python_pythonw_batch_and_executable(tmp_path):
    python = tmp_path / "Python" / "python.exe"
    pythonw = python.with_name("pythonw.exe")
    python.parent.mkdir()
    python.write_bytes(b"")
    pythonw.write_bytes(b"")
    cmd = tmp_path / "Windows" / "System32" / "cmd.exe"
    cmd.parent.mkdir(parents=True)
    cmd.write_bytes(b"")

    py = launch_file_selection(tmp_path / "任务.py", python_executable=python, comspec=cmd)
    pyw = launch_file_selection(tmp_path / "后台.pyw", python_executable=python, comspec=cmd)
    bat = launch_file_selection(tmp_path / "启动.bat", python_executable=python, comspec=cmd)
    exe = launch_file_selection(tmp_path / "程序.exe", python_executable=python, comspec=cmd)

    assert (py.path, py.arguments) == (python, (str(tmp_path / "任务.py"),))
    assert (pyw.path, pyw.arguments) == (pythonw, (str(tmp_path / "后台.pyw"),))
    assert (bat.path, bat.arguments) == (cmd, ("/c", str(tmp_path / "启动.bat")))
    assert (exe.path, exe.arguments) == (tmp_path / "程序.exe", ())
    assert {item.working_directory for item in (py, pyw, bat, exe)} == {tmp_path}
```

Add these edge-case assertions to the same test module:

```python
def test_launch_selection_falls_back_and_preserves_custom_arguments(tmp_path):
    python = tmp_path / "Python" / "python.exe"
    python.parent.mkdir()
    python.write_bytes(b"")
    script = tmp_path / "后台.pyw"
    selection = launch_file_selection(
        script,
        python_executable=python,
        comspec=tmp_path / "cmd.exe",
    )

    assert selection.path == python
    assert replace_automatic_prefix(
        ["old.py", "--profile", "daily"],
        ("old.py",),
        selection.arguments,
    ) == [str(script.resolve()), "--profile", "daily"]


def test_default_comspec_uses_system32_when_environment_value_is_invalid(tmp_path):
    root = tmp_path / "Windows"
    fallback = root / "System32" / "cmd.exe"
    fallback.parent.mkdir(parents=True)
    fallback.write_bytes(b"")

    assert default_comspec({"COMSPEC": str(tmp_path / "missing.exe"), "SystemRoot": str(root)}) == fallback
```

- [ ] **Step 2: Run the mapping tests and verify the helper is missing**

Run: `python -m pytest tests/ui/test_launch_file_selection.py -q`

Expected: collection fails because `flow_runner.ui.launch_file_selection` does not exist.

- [ ] **Step 3: Implement the pure launch mapping module**

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class LaunchFileSelection:
    path: Path
    arguments: tuple[str, ...]
    working_directory: Path


def launch_file_selection(
    selected: Path,
    *,
    python_executable: Path,
    comspec: Path,
) -> LaunchFileSelection:
    selected = selected.resolve()
    suffix = selected.suffix.casefold()
    if suffix == ".py":
        return LaunchFileSelection(python_executable, (str(selected),), selected.parent)
    if suffix == ".pyw":
        pythonw = python_executable.with_name("pythonw.exe")
        executable = pythonw if pythonw.is_file() else python_executable
        return LaunchFileSelection(executable, (str(selected),), selected.parent)
    if suffix == ".bat":
        return LaunchFileSelection(comspec, ("/c", str(selected)), selected.parent)
    return LaunchFileSelection(selected, (), selected.parent)


def replace_automatic_prefix(
    current: list[str], previous: tuple[str, ...], replacement: tuple[str, ...]
) -> list[str]:
    custom = current[len(previous):] if tuple(current[:len(previous)]) == previous else current
    return [*replacement, *custom]


def infer_automatic_prefix(path: Path, arguments: list[str]) -> tuple[str, ...]:
    name = path.name.casefold()
    if name in {"python.exe", "pythonw.exe", "python", "pythonw"} and arguments:
        if Path(arguments[0]).suffix.casefold() in {".py", ".pyw"}:
            return (arguments[0],)
    if name in {"cmd.exe", "cmd"} and len(arguments) >= 2:
        if arguments[0].casefold() == "/c" and Path(arguments[1]).suffix.casefold() == ".bat":
            return arguments[0], arguments[1]
    return ()


def default_python_executable() -> Path:
    return Path(sys.executable).resolve()


def default_comspec(environment: Mapping[str, str] = os.environ) -> Path:
    configured = Path(environment.get("COMSPEC", ""))
    if configured.is_file():
        return configured.resolve()
    return Path(environment.get("SystemRoot", r"C:\Windows")) / "System32" / "cmd.exe"
```

Import `os`, `sys`, and `Mapping` in this module. `infer_automatic_prefix()` is also used when an
existing action is loaded: derive the prior automatic prefix from the saved executable and arguments;
derive the prior automatic working directory from the selected script/batch parent only when the
saved working directory equals that parent.

- [ ] **Step 4: Add a user-selection signal and launch-specific form adapter**

In `PathFieldEditor`, define `fileSelected = Signal(str)`. Emit it after `_browse()` sets the chosen
text. Add a configurable file filter and set the launch path filter to
`程序和脚本 (*.exe *.com *.py *.pyw *.bat);;所有文件 (*)`.

In `ModelForm`, only when `model_type is LaunchProcessConfig`, connect the `path` editor's
`fileSelected` to `_launch_file_selected()`. Track `_launch_automatic_arguments` and
`_launch_automatic_working_directory`; infer them when existing values are loaded. The handler must:

```python
selection = launch_file_selection(
    Path(selected),
    python_executable=default_python_executable(),
    comspec=default_comspec(),
)
arguments = replace_automatic_prefix(
    current_arguments,
    self._launch_automatic_arguments,
    selection.arguments,
)
path_editor.setText(str(selection.path))
arguments_editor.setText(json.dumps(arguments, ensure_ascii=False))
if not current_working_directory or current_working_directory == previous_auto_directory:
    working_directory_editor.setText(str(selection.working_directory))
self._launch_automatic_arguments = selection.arguments
self._launch_automatic_working_directory = selection.working_directory
```

Block only redundant internal signals while setting the three fields, then emit one `changed` signal
so the current action becomes pending.

- [ ] **Step 5: Make summaries show the real target file name**

Add this helper in `localization.py` and use the same basename rule for `recording.playback`:

```python
def _launch_target_name(config: dict[str, Any]) -> str:
    raw_path = str(config.get("path", "")).strip()
    arguments = config.get("arguments", [])
    values = [str(value) for value in arguments] if isinstance(arguments, list) else []
    executable = Path(raw_path)
    executable_name = executable.name.casefold()
    if executable_name in {"python.exe", "pythonw.exe", "python", "pythonw"} and values:
        return Path(values[0]).name
    if executable_name in {"cmd.exe", "cmd"} and len(values) >= 2 and values[0].casefold() == "/c":
        return Path(values[1]).name
    return executable.name
```

Return `capability_label(action.capability)` when the helper returns an empty name. Assertions must
include:

```python
assert action_summary(python_action) == "启动程序：任务.py"
assert action_summary(batch_action) == "启动程序：启动.bat"
assert action_summary(executable_action) == "启动程序：程序.exe"
assert action_summary(playback_action) == "播放录制：latest.json"
```

- [ ] **Step 6: Run launch, editor, and summary tests**

Run: `python -m pytest tests/ui/test_launch_file_selection.py tests/ui/test_step_editors.py -q`

Expected: all tests pass, including custom argument and custom working-directory preservation.

- [ ] **Step 7: Commit launch convenience as one behavior unit**

```powershell
git add flow_runner/ui/launch_file_selection.py flow_runner/ui/editors/model_form.py flow_runner/ui/localization.py tests/ui/test_launch_file_selection.py tests/ui/test_step_editors.py
git commit -m "feat: autofill launch files and simplify summaries"
```

### Task 5: Show Result Bindings With Chinese Names

**Files:**
- Create: `flow_runner/ui/result_bindings.py`
- Modify: `flow_runner/ui/editors/model_form.py`
- Modify: `flow_runner/ui/editors/action_editor.py`
- Modify: `flow_runner/ui/editors/condition_editor.py`
- Modify: `flow_runner/ui/editors/route_editor.py`
- Modify: `flow_runner/ui/panels/property_panel.py`
- Modify: `flow_runner/ui/localization.py`
- Test: `tests/ui/test_result_bindings.py`
- Modify: `tests/ui/test_step_editors.py`

- [ ] **Step 1: Write binding-option generation and round-trip tests**

```python
def test_binding_options_use_capability_and_condition_node_names():
    condition = ConditionGroup(
        id="可点击目标",
        operator="or",
        children=[
            LeafCondition(id="登录按钮", capability="vision.ocr", config={"keywords": "登录"}),
            LeafCondition(id="开始图片", capability="vision.image", config={"template_path": "a.png"}),
        ],
    )

    options = result_binding_options(condition)
    labels = {option.expression: option.label for option in options}

    assert labels["$result.primary.position"] == "当前步骤检测结果 → 主要结果 → 坐标"
    assert labels['$result.children["登录按钮"].text'] == "OCR 文字检测「登录按钮」→ 识别文字"
    assert labels['$result.children["开始图片"].position'] == "图片模板检测「开始图片」→ 坐标"


def test_binding_field_preserves_unknown_expression_as_custom(qtbot):
    editor = BindingFieldEditor()
    qtbot.addWidget(editor)
    editor.set_options([])
    editor.setValue('$result.children["旧节点"].text')

    assert editor.is_custom
    assert editor.value() == '$result.children["旧节点"].text'
```

Add a UI test that loads a step with an OCR node named `登录按钮`, selects dynamic binding in the
mouse position editor, and verifies the visible combo text is Chinese while `form.values()` remains
`$result.primary.position`.

- [ ] **Step 2: Run the tests and verify missing mapping/editor types**

Run: `python -m pytest tests/ui/test_result_bindings.py -q`

Expected: collection fails because `result_bindings` and `BindingFieldEditor` are not defined.

- [ ] **Step 3: Implement the pure binding option model**

```python
@dataclass(frozen=True, slots=True)
class ResultBindingOption:
    expression: str
    label: str
    field: str


RESULT_FIELDS = {
    "vision.ocr": ("position", "bounds", "text", "confidence"),
    "vision.image": ("position", "bounds", "confidence"),
    "vision.pixel": ("position",),
}


def result_binding_options(condition: ConditionNode | None) -> tuple[ResultBindingOption, ...]:
    if condition is None:
        return ()
    options: list[ResultBindingOption] = []
    if isinstance(condition, LeafCondition) or condition.operator == "or":
        fields = _primary_fields(condition)
        options.extend(
            ResultBindingOption(
                f"$result.primary.{field}",
                f"当前步骤检测结果 → 主要结果 → {result_field_label(field)}",
                field,
            )
            for field in fields
        )
    if isinstance(condition, ConditionGroup):
        for child in condition.children:
            if not isinstance(child, LeafCondition):
                continue
            for field in RESULT_FIELDS.get(child.capability, ()):
                expression = f'$result.children[{json.dumps(child.id, ensure_ascii=False)}].{field}'
                label = (
                    f"{capability_label(child.capability)}「{child.id}」→ "
                    f"{result_field_label(field)}"
                )
                options.append(ResultBindingOption(expression, label, field))
    return tuple(options)


def _primary_fields(condition: ConditionNode) -> tuple[str, ...]:
    if isinstance(condition, LeafCondition):
        return RESULT_FIELDS.get(condition.capability, ())
    fields = {
        field
        for child in condition.children
        if isinstance(child, LeafCondition)
        for field in RESULT_FIELDS.get(child.capability, ())
    }
    return tuple(field for field in ("position", "bounds", "text", "confidence") if field in fields)
```

Add `RESULT_FIELD_LABELS` and `result_field_label()` to `localization.py` for `position`, `bounds`,
`text`, and `confidence`.

- [ ] **Step 4: Implement a reusable binding selector**

Add this reusable editor to `model_form.py`:

```python
class BindingFieldEditor(QWidget):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.combo = FocusWheelComboBox()
        self.custom_edit = QLineEdit()
        self.custom_edit.setPlaceholderText("输入自定义绑定表达式")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.combo)
        layout.addWidget(self.custom_edit)
        self.combo.currentIndexChanged.connect(self._mode_changed)
        self.custom_edit.textChanged.connect(self.changed.emit)
        self.set_options(())

    @property
    def is_custom(self) -> bool:
        return self.combo.currentData() is None

    def set_options(self, options: tuple[ResultBindingOption, ...]) -> None:
        current = self.value() if self.combo.count() else ""
        blocked = self.combo.blockSignals(True)
        self.combo.clear()
        for option in options:
            self.combo.addItem(option.label, option.expression)
        self.combo.addItem("自定义表达式", None)
        self.combo.blockSignals(blocked)
        self.setValue(current)

    def value(self) -> str:
        value = self.combo.currentData()
        return value if isinstance(value, str) else self.custom_edit.text().strip()

    def setValue(self, expression: str) -> None:  # noqa: N802 - Qt-compatible API
        index = self.combo.findData(expression)
        if index >= 0:
            self.combo.setCurrentIndex(index)
        else:
            self.combo.setCurrentIndex(self.combo.count() - 1)
            self.custom_edit.setText(expression)
        self._mode_changed()

    def _mode_changed(self, _index: int = -1) -> None:
        self.custom_edit.setVisible(self.is_custom)
        self.changed.emit()
```

Replace the tuple editor's raw binding line edit with `BindingFieldEditor`, retaining
`binding_edit` as an alias to its custom edit for test/backward compatibility. Add
`ModelForm.set_binding_options()` and filter tuple fields to options whose `field` matches the field
type (`position` for the mouse coordinate editor).

- [ ] **Step 5: Propagate the current condition to action and route editors**

Add `ActionEditor.set_binding_options(options)` and pass them into every rebuilt `ModelForm`.
Add `RouteEditor.set_binding_options(options)` and show a `BindingFieldEditor` when predicate source
is `binding`; retain the normal key `QLineEdit` for variable predicates.

Add `ConditionEditor.condition_for_bindings()` that commits the selected node when valid and returns
the latest `_root`, falling back to the last valid root during incomplete edits. In `PropertyPanel`,
centralize propagation:

```python
def _refresh_binding_options(self, condition: ConditionNode | None) -> None:
    options = result_binding_options(condition)
    if self.action_editor is not None:
        self.action_editor.set_binding_options(options)
    if self.route_editor is not None:
        self.route_editor.set_binding_options(options)
```

Call it from `set_step()`, guided/JSON synchronization, `clear_step()`, and the condition editor's
change handler. The change handler must still call `_mark_pending()`.

- [ ] **Step 6: Verify action and route serialization is unchanged**

Run: `python -m pytest tests/ui/test_result_bindings.py tests/ui/test_step_editors.py tests/ui/test_property_panel_modes.py -q`

Expected: all tests pass; existing expression assertions still compare the original English schema
syntax while widget text assertions use Chinese labels.

- [ ] **Step 7: Commit the binding presentation layer**

```powershell
git add flow_runner/ui/result_bindings.py flow_runner/ui/editors/model_form.py flow_runner/ui/editors/action_editor.py flow_runner/ui/editors/condition_editor.py flow_runner/ui/editors/route_editor.py flow_runner/ui/panels/property_panel.py flow_runner/ui/localization.py tests/ui/test_result_bindings.py tests/ui/test_step_editors.py tests/ui/test_property_panel_modes.py
git commit -m "feat: present result bindings with Chinese names"
```

### Task 6: Complete the App-Owned Chinese UI Surface

**Files:**
- Modify: `flow_runner/ui/localization.py`
- Create: `tests/ui/test_localized_ui.py`

- [ ] **Step 1: Add deterministic label-coverage tests**

```python
ALL_UI_CONFIG_MODELS = (
    MouseActionConfig, KeyboardActionConfig, LaunchProcessConfig, PlaybackScriptConfig,
    SetVariableConfig, WaitActionConfig, WindowActionConfig, CountConditionConfig,
    ImageConditionConfig, OcrConditionConfig, PixelConditionConfig, ProcessConditionConfig,
    RegionChangeConditionConfig, TimeConditionConfig, VariableConditionConfig,
    WindowConditionConfig,
)

KNOWN_FIELD_NAMES = {
    name
    for model in ALL_UI_CONFIG_MODELS
    for name in model.model_fields
}


def test_every_registered_config_field_has_a_chinese_or_approved_technical_label():
    missing = {name for name in KNOWN_FIELD_NAMES if field_label(name) == name}
    assert missing == set()


def test_every_ui_choice_has_a_localized_label():
    choices = {
        choice
        for model in ALL_UI_CONFIG_MODELS
        for field in model.model_fields.values()
        for choice in literal_or_enum_choices(field.annotation)
    }
    missing = {value for value in choices if choice_label(value) == str(value)}
    assert missing == set()


def test_normal_binding_controls_do_not_expose_internal_result_syntax(qtbot):
    panel = build_property_panel_with_visual_step(qtbot)
    visible_text = "\n".join(
        widget.text() for widget in panel.findChildren(QLineEdit) if widget.isVisible()
    )
    assert "$result." not in visible_text
```

Use this exact helper in the test:

```python
def literal_or_enum_choices(annotation: object) -> tuple[object, ...]:
    origin = get_origin(annotation)
    if origin is Literal:
        return get_args(annotation)
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return tuple(annotation)
    return tuple(
        choice
        for argument in get_args(annotation)
        if argument is not type(None)
        for choice in literal_or_enum_choices(argument)
    )
```

Approved technical labels remain OCR, RGB, ID, JSON, Python, Tesseract, PaddleOCR-json, AND, OR,
and NOT.

- [ ] **Step 2: Run the localization test and record exact missing mappings**

Run: `python -m pytest tests/ui/test_localized_ui.py -q`

Expected: FAIL with a finite set of schema fields or choices that currently fall back to English.

- [ ] **Step 3: Add exact mappings and replace app-owned visible English**

For every failure, add an explicit `FIELD_LABELS`, `CHOICE_LABELS`, capability, result-field, or
diagnostic label. Search app-owned visible strings with:

```powershell
rg -n 'setText\(|setPlaceholderText\(|setToolTip\(|QLabel\(|QPushButton\(|addItem\(|addTab\(|setWindowTitle\(' flow_runner/ui --glob '*.py'
```

Translate user-facing prose that is maintained by this repository. Keep file names, user values,
schema keys in advanced JSON, custom expressions, third-party raw error details, and the approved
technical names unchanged. Wrap unavoidable raw system errors with a Chinese context message.

- [ ] **Step 4: Run all UI localization and editor tests**

Run: `python -m pytest tests/ui/test_localized_ui.py tests/ui/test_step_editors.py tests/ui/test_property_panel_modes.py tests/ui/test_app_smoke.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the localization coverage**

```powershell
git add flow_runner/ui/localization.py tests/ui/test_localized_ui.py tests/ui/test_step_editors.py tests/ui/test_property_panel_modes.py tests/ui/test_app_smoke.py
git commit -m "fix: complete Chinese UI labels"
```

Before committing, inspect `git diff --cached --name-only` and unstage any file outside the listed UI
and test scope; never stage `data/project.json`.

### Task 7: Persist and Restore Main-Window Size

**Files:**
- Create: `flow_runner/ui/window_preferences.py`
- Modify: `flow_runner/ui/main_window.py`
- Modify: `flow_runner/app.py`
- Create: `tests/ui/test_window_preferences.py`
- Modify: `tests/ui/test_main_window.py`

- [ ] **Step 1: Write preference validation and MainWindow restore tests**

```python
def test_window_preferences_round_trip_size(tmp_path):
    settings = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    preferences = WindowPreferences(settings)
    assert preferences.size is None

    preferences.size = QSize(1180, 760)
    settings.sync()

    reopened = WindowPreferences(
        QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    )
    assert reopened.size == QSize(1180, 760)


def test_main_window_restores_and_saves_local_size_without_dirtying_project(qtbot, tmp_path):
    settings = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    preferences = WindowPreferences(settings)
    preferences.size = QSize(980, 680)
    project = sample_project()
    window = MainWindow(project, window_preferences=preferences)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(1)

    assert window.size() == QSize(980, 680)
    window.resize(1040, 720)
    window.close()
    assert preferences.size == QSize(1040, 720)
    assert not window.view_model.dirty
```

Add these cases to the same test module:

```python
@pytest.mark.parametrize(("width", "height"), [("bad", 700), (-1, 700), (900, 0), (True, 700)])
def test_window_preferences_reject_invalid_sizes(tmp_path, width, height):
    settings = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    settings.setValue("window/width", width)
    settings.setValue("window/height", height)
    assert WindowPreferences(settings).size is None


def test_main_window_clamps_oversized_saved_size_to_screen(qtbot, tmp_path):
    settings = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    preferences = WindowPreferences(settings)
    preferences.size = QSize(100_000, 100_000)
    window = MainWindow(sample_project(), window_preferences=preferences)
    qtbot.addWidget(window)
    window.show()
    available = QApplication.primaryScreen().availableGeometry().size()
    assert window.width() <= available.width()
    assert window.height() <= available.height()


def test_cancelled_close_does_not_save_window_size(qtbot, tmp_path):
    settings = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    preferences = WindowPreferences(settings)
    window = MainWindow(
        sample_project(),
        window_preferences=preferences,
        confirm_close=lambda **state: CloseDecision.CANCEL,
    )
    qtbot.addWidget(window)
    window.view_model.rename_group(window.view_model.project.groups[0].id, "已修改")
    window.resize(1040, 720)
    assert not window.close()
    assert preferences.size is None
```

- [ ] **Step 2: Run tests and verify preferences are absent**

Run: `python -m pytest tests/ui/test_window_preferences.py -q`

Expected: collection fails because `WindowPreferences` does not exist.

- [ ] **Step 3: Implement validated QSettings access**

```python
from PySide6.QtCore import QSettings, QSize


class WindowPreferences:
    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings if settings is not None else QSettings()

    @property
    def size(self) -> QSize | None:
        width = self._positive_int(self._settings.value("window/width"))
        height = self._positive_int(self._settings.value("window/height"))
        return QSize(width, height) if width is not None and height is not None else None

    @size.setter
    def size(self, value: QSize) -> None:
        self._settings.setValue("window/width", value.width())
        self._settings.setValue("window/height", value.height())

    @staticmethod
    def _positive_int(value: object) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            parsed = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None
        return parsed if parsed > 0 else None
```

- [ ] **Step 4: Inject preferences and clamp restored dimensions**

Add this pure helper beside the existing main-window settings helpers:

```python
def _clamped_window_size(requested: QSize, available: QSize) -> QSize:
    minimum_width = min(640, available.width())
    minimum_height = min(480, available.height())
    return QSize(
        max(minimum_width, min(requested.width(), available.width())),
        max(minimum_height, min(requested.height(), available.height())),
    )
```

Add `window_preferences: WindowPreferences | None = None` to `MainWindow.__init__`. In
`_apply_initial_window_geometry()`, prefer `self.window_preferences.size`, pass it through
`_clamped_window_size()`, and retain the current 85% by 80% default calculation only when no valid
saved size exists.

At the end of `closeEvent()`, after `super().closeEvent(event)`, save only if `event.isAccepted()`.
Use `normalGeometry().size()` when maximized and `size()` otherwise. Do not save on cancel, save
failure, or runner shutdown failure.

In `create_application()`, before constructing default QSettings users, set stable identities:

```python
app.setOrganizationName("Flow Runner")
app.setApplicationName("Flow Runner")
```

- [ ] **Step 5: Run preference, close, and application smoke tests**

Run: `python -m pytest tests/ui/test_window_preferences.py tests/ui/test_main_window.py tests/ui/test_app_smoke.py -q`

Expected: all tests pass and project dirty/save-state assertions remain unchanged.

- [ ] **Step 6: Commit local window persistence**

```powershell
git add flow_runner/ui/window_preferences.py flow_runner/ui/main_window.py flow_runner/app.py tests/ui/test_window_preferences.py tests/ui/test_main_window.py tests/ui/test_app_smoke.py
git commit -m "feat: persist main window size"
```

### Task 8: Documentation, Full Verification, and Real-Window Handoff

**Files:**
- Modify: `README.md`
- Modify: `REAL_ENVIRONMENT_CHECKLIST.md`

- [ ] **Step 1: Update user documentation to match actual behavior**

In `README.md`, replace project/runtime toolbar descriptions with the three column assignments;
state that controls wrap as columns resize, all steps remain expanded with names at the top,
launch-file selection fills executable/arguments/working directory, friendly Chinese bindings keep
the internal schema syntax, and local window size restores automatically.

Do not document mouse point picking, original-resolution capture overlays, hide-before-capture, or
window-relative fixed mouse coordinates because they belong to task two.

- [ ] **Step 2: Add concrete Windows acceptance checks**

Append checks to `REAL_ENVIRONMENT_CHECKLIST.md` for:

```markdown
- [ ] Drag each of the three column splitters narrow and wide; its controls wrap without overlap.
- [ ] Load a multi-step workflow; every card is expanded and every step name remains visible.
- [ ] Select one `.py`, `.pyw`, `.bat`, and `.exe` launch target; verify generated fields and run it.
- [ ] Close at a non-default window size and relaunch; verify width and height are restored.
- [ ] Confirm normal binding selectors show condition names in Chinese and saved JSON stays unchanged.
```

- [ ] **Step 3: Run formatting, typing, and the complete automated suite**

Run: `python -m compileall flow_runner tests`

Expected: exit code 0.

Run: `python -m ruff check .`

Expected: exit code 0.

Run: `python -m mypy flow_runner`

Expected: exit code 0.

Run: `$env:QT_QPA_PLATFORM='offscreen'; python -m pytest -q`

Expected: all tests pass with no unexpected skips or failures.

- [ ] **Step 4: Review the final diff and protect user runtime data**

Run:

```powershell
git status --short
git diff --check
git diff --stat
git diff -- data/project.json
```

Expected: `data/project.json` may still show the user's pre-existing column-width change, but it is
not staged and no implementation commit contains it. Review every other changed path against this
plan.

- [ ] **Step 5: Perform the real GUI acceptance checklist**

Launch with the global Python entry point, verify the five newly added checklist items, and record
each result. Pay particular attention to control overlap at narrow widths and argument preservation
when reselecting launch files. This is a required manual handoff because offscreen Qt cannot prove
real Windows text fitting and splitter ergonomics.

- [ ] **Step 6: Commit documentation after verification**

```powershell
git add README.md REAL_ENVIRONMENT_CHECKLIST.md
git commit -m "docs: update responsive UI usage"
```

Do not push until the user explicitly requests it.

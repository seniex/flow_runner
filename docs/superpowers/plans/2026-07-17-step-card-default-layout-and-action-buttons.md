# Step Card, Default Layout, and Action Buttons Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make multi-route step cards fully responsive, establish the confirmed window and splitter defaults, and replace the action capability combo box with wrapping selection buttons.

**Architecture:** Keep step-card width/height synchronization inside `StepListPanel`, and reuse Qt height-for-width behavior for wrapped labels. Define layout defaults centrally in `main_window.py`, preserving saved preferences as higher priority. Replace only the action capability presentation control with a small exclusive button selector backed by the same stable capability strings and existing `ActionEditor` state transitions.

**Tech Stack:** Python 3.11+, PySide6/Qt Widgets, pytest-qt, Ruff, mypy

---

## File Structure

- Modify `flow_runner/ui/panels/step_list_panel.py`: constrain cards to the list viewport, disable horizontal scrolling, and recalculate item heights after viewport resize.
- Modify `tests/ui/test_simple_shell.py`: cover multi-route wrapping, complete bottom content, horizontal-scroll policy, and splitter defaults.
- Modify `flow_runner/ui/main_window.py`: define and apply the confirmed fallback window and splitter sizes.
- Modify `tests/ui/test_main_window.py`: cover fallback window size, clamping, and saved-size precedence.
- Modify `flow_runner/ui/editors/action_editor.py`: replace the capability combo with an exclusive, wrapping capability button group.
- Modify `flow_runner/resources/styles/base.qss`: style normal and checked capability buttons through the shared theme.
- Modify `tests/ui/test_step_editors.py`: cover button selection, form switching, and loading existing actions.
- Modify `README.md`: record responsive step cards, confirmed fallback dimensions, and action capability buttons.

### Task 1: Responsive multi-route step cards

**Files:**
- Modify: `flow_runner/ui/panels/step_list_panel.py`
- Test: `tests/ui/test_simple_shell.py`

- [ ] **Step 1: Write failing tests for viewport width and complete wrapped content**

Add tests that create a workflow with several long route summaries, show a narrow `StepListPanel`, and assert the list never exposes a horizontal scrollbar and the item height contains the final route label:

```python
def test_step_cards_wrap_routes_to_viewport_without_horizontal_scroll(qtbot):
    project, workflow = _project_with_long_multi_route_step()
    panel = StepListPanel(project)
    qtbot.addWidget(panel)
    panel.resize(280, 500)
    panel.set_workflow(workflow)
    panel.show()
    qtbot.wait(1)

    assert panel.list.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert panel.list.horizontalScrollBar().maximum() == 0
    item = panel.list.item(0)
    card = panel.list.itemWidget(item)
    route_label = card.findChild(QLabel, "routeSummaryRow")
    assert card.width() <= panel.list.viewport().width()
    assert item.sizeHint().height() >= route_label.geometry().bottom() + 8


def test_step_card_height_reflows_when_step_column_width_changes(qtbot):
    project, workflow = _project_with_long_multi_route_step()
    panel = StepListPanel(project)
    qtbot.addWidget(panel)
    panel.resize(280, 500)
    panel.set_workflow(workflow)
    panel.show()
    qtbot.wait(1)
    narrow_height = panel.list.item(0).sizeHint().height()

    panel.resize(700, 500)
    qtbot.wait(1)

    assert panel.list.item(0).sizeHint().height() < narrow_height
```

Use existing project/route builders in `tests/ui/test_simple_shell.py`; add only a focused helper `_project_with_long_multi_route_step()` that returns a project and its workflow.

- [ ] **Step 2: Run the focused tests and verify failure**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_simple_shell.py -k "step_cards_wrap or step_card_height_reflows" -v
```

Expected: FAIL because the list still uses its default horizontal-scroll policy and item size hints are not recomputed from the viewport width.

- [ ] **Step 3: Implement viewport-driven card sizing**

In `StepListPanel.__init__`, disable the horizontal scrollbar and install an event filter on the list viewport:

```python
self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
self.list.viewport().installEventFilter(self)
```

Add an event filter and one refresh method. Constrain each card to the current viewport width, activate its layout, ask the layout for height-for-width, and update the item hint:

```python
def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # noqa: N802
    if watched is self.list.viewport() and event.type() == QEvent.Type.Resize:
        QTimer.singleShot(0, self._refresh_card_sizes)
    return super().eventFilter(watched, event)

def _refresh_card_sizes(self) -> None:
    width = max(1, self.list.viewport().width())
    for item in self._items.values():
        card = self.list.itemWidget(item)
        if not isinstance(card, StepCardWidget):
            continue
        card.setFixedWidth(width)
        card.layout().activate()
        height = card.layout().heightForWidth(width)
        item.setSizeHint(QSize(width, max(card.minimumSizeHint().height(), height)))
```

Import `QEvent`, `QObject`, `QSize`, and `QTimer`. Call `_refresh_card_sizes()` after populating `set_workflow()` and replace the selection-time `card.sizeHint()` refresh with the shared method. If the list viewport reserves frame space, subtract only the measured viewport width; do not hard-code a scrollbar width.

- [ ] **Step 4: Run the focused tests and existing step-card tests**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_simple_shell.py -v
```

Expected: all tests in the file PASS.

- [ ] **Step 5: Commit the responsive-card change**

```powershell
git add flow_runner/ui/panels/step_list_panel.py tests/ui/test_simple_shell.py
git commit -m "fix: make step cards reflow to column width"
```

### Task 2: Confirmed fallback window and splitter sizes

**Files:**
- Modify: `flow_runner/ui/main_window.py`
- Test: `tests/ui/test_main_window.py`
- Test: `tests/ui/test_simple_shell.py`

- [ ] **Step 1: Write failing tests for fallback defaults and saved-value precedence**

Add these assertions using an empty temporary `QSettings` instance so machine-local preferences cannot affect the test:

```python
def test_main_window_uses_confirmed_default_size_without_saved_preference(qtbot, tmp_path):
    settings = QSettings(str(tmp_path / "window.ini"), QSettings.Format.IniFormat)
    window = MainWindow(sample_project(), window_preferences=WindowPreferences(settings))
    qtbot.addWidget(window)
    available = QApplication.primaryScreen().availableGeometry().size()

    assert window.size() == QSize(min(1723, available.width()), min(1102, available.height()))
```

Extend the existing saved-size test to continue asserting that `700 × 600` wins over the fallback. In `tests/ui/test_simple_shell.py`, add:

```python
def test_main_window_uses_confirmed_default_column_widths(qtbot):
    project, _first, _second, _step = _project()
    window = MainWindow(project)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(1)

    actual = window.workspace_splitter.sizes()
    assert [round(value / sum(actual), 3) for value in actual] == [
        round(value / 1660, 3) for value in (249, 259, 1152)
    ]
```

Keep the existing `[180, 320, 700]` restoration test as the saved-project precedence check.

- [ ] **Step 2: Run the new layout tests and verify failure**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_main_window.py::test_main_window_uses_confirmed_default_size_without_saved_preference tests/ui/test_simple_shell.py::test_main_window_uses_confirmed_default_column_widths -v
```

Expected: FAIL because the window fallback is screen-percentage based and the splitter currently keeps Qt's initial sizes.

- [ ] **Step 3: Add centralized fallback constants and apply them**

Near the top of `main_window.py`, define:

```python
DEFAULT_WINDOW_SIZE = QSize(1723, 1102)
DEFAULT_COLUMN_WIDTHS = (249, 259, 1152)
```

Change `_apply_initial_window_geometry()` so absence of a saved size uses `_clamped_window_size(DEFAULT_WINDOW_SIZE, available.size())`. Change the no-screen fallback to `self.window_preferences.size or DEFAULT_WINDOW_SIZE`.

Change `_restore_column_widths()` to always call `setSizes` with either saved or default values:

```python
widths = self._saved_column_widths or DEFAULT_COLUMN_WIDTHS
self.workspace_splitter.setSizes(list(widths))
if self._saved_column_widths is None:
    self._saved_column_widths = DEFAULT_COLUMN_WIDTHS
```

Do not mark the default application as a pending project layout change.

- [ ] **Step 4: Run layout persistence and window-preference tests**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_main_window.py tests/ui/test_simple_shell.py -v
```

Expected: all tests PASS, including saved-size, saved-column-width, and dirty-state behavior.

- [ ] **Step 5: Commit the default-layout change**

```powershell
git add flow_runner/ui/main_window.py tests/ui/test_main_window.py tests/ui/test_simple_shell.py
git commit -m "feat: set confirmed workspace layout defaults"
```

### Task 3: Wrapping action capability buttons

**Files:**
- Modify: `flow_runner/ui/editors/action_editor.py`
- Modify: `flow_runner/resources/styles/base.qss`
- Test: `tests/ui/test_step_editors.py`

- [ ] **Step 1: Write failing tests for generated buttons and capability switching**

Add tests that use the existing test registry and locate buttons by their stable capability property:

```python
def _action_capability_button(editor: ActionEditor, capability: str) -> QPushButton:
    return next(
        button
        for button in editor.capability_buttons.buttons()
        if button.property("capability") == capability
    )


def test_action_editor_uses_wrapping_capability_buttons(qtbot):
    editor = ActionEditor(registry())
    qtbot.addWidget(editor)

    assert not hasattr(editor, "capability_combo")
    assert isinstance(editor.capability_layout, CompactFlowLayout)
    assert {button.property("capability") for button in editor.capability_buttons.buttons()} == {
        metadata.name for metadata in registry().action_metadata()
    }


def test_action_capability_button_switches_form_and_is_exclusive(qtbot):
    editor = ActionEditor(registry())
    qtbot.addWidget(editor)
    wait_button = _action_capability_button(editor, "system.wait")
    mouse_button = _action_capability_button(editor, "input.mouse")

    mouse_button.click()

    assert mouse_button.isChecked()
    assert not wait_button.isChecked()
    assert editor.current_capability() == "input.mouse"
    assert editor.config_form.editor("operation") is not None


def test_action_editor_selects_button_when_loading_existing_action(qtbot):
    editor = ActionEditor(registry())
    qtbot.addWidget(editor)
    editor.set_actions([ActionSpec(capability="system.wait", config={"keywords": "等待"})])

    assert _action_capability_button(editor, "system.wait").isChecked()
    assert editor.config_form.editor("keywords").text() == "等待"
```

Import `QPushButton`, `CompactFlowLayout`, and `ActionEditor` where needed.

- [ ] **Step 2: Run the new action-editor tests and verify failure**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_step_editors.py -k "action_editor_uses_wrapping or action_capability_button or selects_button_when_loading" -v
```

Expected: FAIL because `ActionEditor` still exposes `capability_combo` and no button group.

- [ ] **Step 3: Replace the combo box with an exclusive wrapping button selector**

In `action_editor.py`, remove `FocusWheelComboBox`, import `QButtonGroup`, and import `CompactFlowLayout`. Build a dedicated container:

```python
self.capability_container = QWidget()
self.capability_container.setObjectName("actionCapabilitySelector")
self.capability_layout = CompactFlowLayout(self.capability_container, spacing=6)
self.capability_buttons = QButtonGroup(self)
self.capability_buttons.setExclusive(True)
for metadata in registry.action_metadata():
    button = QPushButton(capability_label(metadata.name))
    button.setObjectName("actionCapabilityButton")
    button.setCheckable(True)
    button.setProperty("capability", metadata.name)
    self.capability_buttons.addButton(button)
    self.capability_layout.addWidget(button)
first_button = self.capability_buttons.buttons()[0]
first_button.setChecked(True)
layout.addWidget(self.capability_container)
self.capability_buttons.buttonClicked.connect(self._capability_changed)
```

Add stable lookup helpers and use them everywhere the combo was read or changed:

```python
def current_capability(self) -> str | None:
    button = self.capability_buttons.checkedButton()
    capability = button.property("capability") if button is not None else None
    return capability if isinstance(capability, str) else None

def _button_for_capability(self, capability: str) -> QPushButton | None:
    for button in self.capability_buttons.buttons():
        if button.property("capability") == capability:
            return button
    return None
```

Use `current_capability()` in `_rebuild_form()` and `_build_current_action()`. In `_load_current()`, find the button, report the existing unknown-capability error if absent, temporarily block the button group signals, check the button, rebuild the form, and load values. Preserve `_loading`, `_current_pending`, and `changed` semantics.

- [ ] **Step 4: Add shared checked-state styling**

In `base.qss`, add selectors that use existing theme colors already present in the file:

```css
#actionCapabilityButton {
    min-width: 64px;
}

#actionCapabilityButton:checked {
    background-color: #247fb3;
    border-color: #62bde8;
    color: #ffffff;
}
```

If the exact colors differ from existing selected controls, reuse the nearest existing selected-button values rather than adding a new palette.

- [ ] **Step 5: Run action-editor and property-panel regression tests**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_step_editors.py tests/ui/test_property_panel_modes.py tests/ui/test_compact_layout.py -v
```

Expected: all tests PASS, including pending edits, loading actions, and compact layout behavior.

- [ ] **Step 6: Commit the action-button change**

```powershell
git add flow_runner/ui/editors/action_editor.py flow_runner/resources/styles/base.qss tests/ui/test_step_editors.py
git commit -m "feat: replace action type dropdown with buttons"
```

### Task 4: Documentation and full verification

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update the editor and layout documentation**

In the README editor section, state explicitly:

```markdown
Step cards constrain themselves to the middle-column viewport: long route lines wrap within the
card, resizing the column recalculates card height, and the step list never uses horizontal
scrolling. Without saved preferences, the workspace starts at 1723 × 1102 (clamped to the current
screen) with three-column proportions based on 249 / 259 / 1152. Saved local window dimensions and
saved project column widths still take precedence. The action guide exposes registered action types
as an exclusive wrapping button group; selecting a button switches the same capability-specific
form used by existing actions.
```

Fit this text into the existing paragraphs rather than creating a duplicate architecture section.

- [ ] **Step 2: Run formatting and focused static checks**

Run:

```powershell
python -m ruff check flow_runner/ui/panels/step_list_panel.py flow_runner/ui/main_window.py flow_runner/ui/editors/action_editor.py tests/ui/test_simple_shell.py tests/ui/test_main_window.py tests/ui/test_step_editors.py
python -m ruff format --check flow_runner/ui/panels/step_list_panel.py flow_runner/ui/main_window.py flow_runner/ui/editors/action_editor.py tests/ui/test_simple_shell.py tests/ui/test_main_window.py tests/ui/test_step_editors.py
python -m mypy flow_runner
```

Expected: all commands exit with code 0.

- [ ] **Step 3: Run the complete automated suite**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest
```

Expected: all tests PASS with no failures.

- [ ] **Step 4: Check compilation, dependencies, and patch cleanliness**

Run:

```powershell
python -m compileall -q flow_runner tests
python -m pip check
git diff --check
git status --short
```

Expected: compileall, pip check, and diff check exit with code 0. `git status` may still show the user's pre-existing `data/project.json` modification; no implementation commit may include it.

- [ ] **Step 5: Commit documentation**

```powershell
git add README.md
git commit -m "docs: record responsive editor layout behavior"
```

- [ ] **Step 6: Hand off real-GUI acceptance checks**

Ask the user to verify on the target display:

1. Narrow and widen the middle column with a multi-route step selected; no horizontal scrollbar appears and the final route line remains visible.
2. Clear or isolate Flow Runner local preferences and open a project without `ui_layout`; the window and three columns use the confirmed defaults, clamped only when the display is smaller.
3. Narrow the property column; action type buttons wrap, remain readable, and selecting each button switches to the correct form.
4. Load and edit existing actions, then add, update, copy, reorder, delete, save, and reopen them without behavior changes.

# Route Summary and Display Mapping Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show complete, numbered, multiline route information on step cards and make region/point capture map Qt screens to Windows physical displays when their names differ.

**Architecture:** Extract route text generation into a Qt-independent formatter shared by the route editor and step cards. Extend Windows display identity with aliases, then use a pure one-to-one matcher that prefers names and safely falls back to DPI-aware geometry before the existing coordinate transforms run.

**Tech Stack:** Python 3.11+, PySide6, Pydantic v2, ctypes Win32 display APIs, Pillow, pytest, pytest-qt, Ruff, mypy

---

## File map

- Create `flow_runner/ui/route_summaries.py`: pure route, predicate, and target text formatting.
- Modify `flow_runner/display_labels.py`: expose the first-step path for workflow entry targets.
- Modify `flow_runner/ui/editors/route_editor.py`: consume the shared formatter.
- Modify `flow_runner/ui/panels/step_list_panel.py`: provide project context and multiline summaries.
- Modify `flow_runner/ui/main_window.py`: keep `StepListPanel` project context synchronized.
- Modify `flow_runner/infrastructure/windowing/displays.py`: attach Windows display aliases.
- Modify `flow_runner/ui/display_mapping.py`: perform one-to-one name/alias/geometry matching.
- Modify focused tests under `tests/ui/` and `tests/unit/infrastructure/`.
- Modify `README.md`: document route summaries and display-name compatibility.

Do not edit `data/project.json`. Do not commit automatically; project instructions require an explicit integration choice before committing.

### Task 1: Add workflow entry display paths

**Files:**
- Modify: `flow_runner/display_labels.py`
- Modify: `tests/unit/test_display_labels.py`

- [ ] **Step 1: Write the failing display-path test**

Add:

```python
def test_workflow_entry_path_includes_first_step_and_handles_empty_workflow():
    first_step = AutomationStep(name="入口步骤")
    populated = Workflow(name="有步骤", steps=[first_step])
    empty = Workflow(name="空流程")
    project = Project(
        name="p",
        groups=[FlowGroup(name="组", workflows=[populated, empty])],
    )
    labels = ProjectDisplayIndex(project)

    assert labels.workflow_entry_path(populated.id) == (
        "01. 组 / 01. 有步骤 / 01. 入口步骤"
    )
    assert labels.workflow_entry_path(empty.id) == "01. 组 / 02. 空流程"
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
python -m pytest tests/unit/test_display_labels.py::test_workflow_entry_path_includes_first_step_and_handles_empty_workflow -v
```

Expected: FAIL because `workflow_entry_path` does not exist.

- [ ] **Step 3: Store workflow entry steps and implement the method**

In `ProjectDisplayIndex.__init__`, add:

```python
self._workflow_entry_steps: dict[UUID, UUID] = {}
```

Inside the workflow loop, before the step loop:

```python
if workflow.steps:
    self._workflow_entry_steps[workflow.id] = workflow.steps[0].id
```

Add:

```python
def workflow_entry_path(self, workflow_id: UUID) -> str:
    step_id = self._workflow_entry_steps.get(workflow_id)
    return self.step_path(step_id) if step_id is not None else self.workflow_path(workflow_id)
```

- [ ] **Step 4: Verify GREEN**

Run the Task 1 focused command. Expected: PASS.

### Task 2: Extract shared route summaries

**Files:**
- Create: `flow_runner/ui/route_summaries.py`
- Create: `tests/ui/test_route_summaries.py`
- Modify: `flow_runner/ui/editors/route_editor.py`

- [ ] **Step 1: Write failing formatter tests**

Create `tests/ui/test_route_summaries.py` with focused tests covering:

```python
def test_route_summaries_include_numbered_target_and_count_predicate():
    target_step = AutomationStep(name="目标步骤")
    target_workflow = Workflow(name="目标流程", steps=[target_step])
    source_step = AutomationStep(name="来源")
    source_workflow = Workflow(name="来源流程", steps=[source_step])
    project = Project(
        name="p",
        groups=[FlowGroup(name="组", workflows=[source_workflow, target_workflow])],
    )
    route = RouteRule(
        outcome=StepOutcome.FAILURE,
        predicate=RoutePredicate.step_count(target_step.id, ComparisonOperator.GE, 3),
        target=RouteTarget.jump_workflow(target_workflow.id),
    )

    assert format_route_summaries(
        [route],
        labels=ProjectDisplayIndex(project),
    ) == (
        "路由 1：失败 且 01. 组 / 02. 目标流程 / 01. 目标步骤执行次数 ≥ 3 "
        "→ 跳转流程：01. 组 / 02. 目标流程 / 01. 目标步骤",
    )
```

Also cover:

```python
def test_route_summaries_put_each_route_on_its_own_line_and_mark_otherwise():
    routes = [
        RouteRule(
            outcome=StepOutcome.SUCCESS,
            predicate=RoutePredicate.task_variable(
                "ready", ComparisonOperator.EQ, True
            ),
            target=RouteTarget.end(),
        ),
        RouteRule(outcome=StepOutcome.SUCCESS, target=RouteTarget.end()),
    ]
    summaries = format_route_summaries(routes, labels=ProjectDisplayIndex(Project(name="p")))
    assert summaries == (
        "路由 1：成功 且 任务变量 ready = true → 结束任务",
        "路由 2：成功（否则） → 结束任务",
    )


def test_empty_route_summary_describes_implicit_behavior():
    assert format_route_summaries(
        [], labels=ProjectDisplayIndex(Project(name="p"))
    ) == ("路由：成功时顺序进入下一步骤；其它结果结束",)
```

- [ ] **Step 2: Verify RED**

Run:

```powershell
python -m pytest tests/ui/test_route_summaries.py -v
```

Expected: collection FAIL because `flow_runner.ui.route_summaries` does not exist.

- [ ] **Step 3: Implement the pure formatter**

Create `flow_runner/ui/route_summaries.py` with this public API:

```python
from collections.abc import Mapping, Sequence
import json

from flow_runner.display_labels import ProjectDisplayIndex
from flow_runner.domain.routing import RoutePredicate, RouteRule, RouteTarget, RouteTargetKind
from flow_runner.ui.localization import choice_label, comparison_symbol


def format_route_summaries(
    routes: Sequence[RouteRule],
    *,
    labels: ProjectDisplayIndex,
    binding_labels: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    if not routes:
        return ("路由：成功时顺序进入下一步骤；其它结果结束",)
    return tuple(
        f"路由 {index + 1}：{format_route_summary(route, index, routes, labels=labels, binding_labels=binding_labels)}"
        for index, route in enumerate(routes)
    )
```

Implement `format_route_summary()` so it:

```python
outcome = choice_label(route.outcome)
if route.predicate is None and any(
    previous.outcome == route.outcome and previous.predicate is not None
    for previous in routes[:index]
):
    outcome += "（否则）"
predicate = (
    f" 且 {_predicate_summary(route.predicate, labels, binding_labels)}"
    if route.predicate is not None
    else ""
)
return f"{outcome}{predicate} → {_target_summary(route.target, labels)}"
```

Predicate subjects must be:

```python
workflow_count -> f"{labels.workflow_path(UUID(predicate.key))}执行次数"
step_count -> f"{labels.step_path(UUID(predicate.key))}执行次数"
binding -> binding_labels.get(predicate.key, predicate.key)
task_variable -> f"任务变量 {predicate.key}"
workflow_variable -> f"流程变量 {predicate.key}"
```

Serialize expected values with `json.dumps(..., ensure_ascii=False)` and use `comparison_symbol()`.

Target summaries must be:

```python
NEXT_STEP -> f"下一步骤：{labels.step_path(target.step_id)}"
JUMP_WORKFLOW -> f"跳转流程：{labels.workflow_entry_path(target.workflow_id)}"
CALL_WORKFLOW -> f"调用流程：{labels.workflow_entry_path(target.workflow_id)}"
RETURN/END -> choice_label(target.kind)
```

Invalid UUID text must fall back to `未知流程` or `未知步骤` without raising.

- [ ] **Step 4: Replace RouteEditor private formatting**

Import `format_route_summary` and replace `_route_summary()` with a call using `self._labels` and the binding-option mapping. Remove duplicated `_predicate_summary`, `_target_summary`, `_workflow_name`, and `_step_name` only after all route-editor tests pass.

- [ ] **Step 5: Verify GREEN and compatibility**

Run:

```powershell
python -m pytest tests/ui/test_route_summaries.py tests/ui/test_step_editors.py -q
```

Expected: PASS.

### Task 3: Render shared multiline summaries on step cards

**Files:**
- Modify: `flow_runner/ui/panels/step_list_panel.py`
- Modify: `flow_runner/ui/main_window.py`
- Modify: `tests/ui/test_simple_shell.py`
- Modify: `tests/ui/test_main_window.py`

- [ ] **Step 1: Write the failing step-card test**

Construct a project with two workflows and two routes, select the source workflow, then assert:

```python
route_label = card.findChild(QLabel, "routeSummaryRow")
assert route_label.text().splitlines() == [
    "路由 1：成功 → 跳转流程：01. 组 / 02. 目标流程 / 01. 目标步骤",
    "路由 2：失败 → 结束任务",
]
```

Add a second assertion that a step without routes displays:

```python
"路由：成功时顺序进入下一步骤；其它结果结束"
```

- [ ] **Step 2: Verify RED**

Run the new focused tests. Expected: FAIL with the current `成功→跳转流程；失败→结束任务` text.

- [ ] **Step 3: Pass project context into StepListPanel**

Change construction to:

```python
self.step_list = StepListPanel(project)
```

Implement:

```python
class StepListPanel(QWidget):
    def __init__(self, project: Project) -> None:
        super().__init__()
        self.setObjectName("stepListPanel")
        self.list = QListWidget()
        layout = QVBoxLayout(self)
        layout.addWidget(self.list)
        self._items: dict[UUID, QListWidgetItem] = {}
        self.list.currentItemChanged.connect(self._on_current_item)
        self.set_project(project)

    def set_project(self, project: Project) -> None:
        self._project = project
        self._labels = ProjectDisplayIndex(project)
```

In `MainWindow._project_changed()`, call `self.step_list.set_project(_project)` before reloading the selected workflow.

- [ ] **Step 4: Use multiline route summaries**

Pass `ProjectDisplayIndex` into `StepCardWidget`, then replace `_route_summary(step)` with:

```python
"\n".join(
    format_route_summaries(
        step.routes,
        labels=labels,
        binding_labels=binding_labels,
    )
)
```

Keep `QLabel.setWordWrap(True)` so each explicit newline is preserved and long paths wrap naturally.

- [ ] **Step 5: Verify GREEN**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_simple_shell.py tests/ui/test_main_window.py -q
```

Expected: PASS.

### Task 4: Reproduce Qt/Win32 display-name mismatch

**Files:**
- Modify: `tests/ui/test_display_mapping.py`
- Modify: `tests/unit/infrastructure/test_displays.py`

- [ ] **Step 1: Extend test doubles with DPI**

Add to `_Screen`:

```python
def __init__(self, name, rect, device_pixel_ratio=1.0):
    self._name = name
    self._rect = rect
    self._device_pixel_ratio = device_pixel_ratio

def devicePixelRatio(self):
    return self._device_pixel_ratio
```

Replace `_PhysicalDisplays` with an injectable test provider:

```python
class _PhysicalDisplays:
    def __init__(self, *displays):
        self._displays = displays

    def displays(self):
        return self._displays
```

- [ ] **Step 2: Write the failing alias reproduction**

```python
def test_display_mapping_matches_qt_model_name_to_windows_device_alias():
    frame = CapturedFrame(Image.new("RGB", (2560, 1440)), origin=(0, 0))
    screen = _Screen("27E1Q", QRect(0, 0, 2560, 1440))
    provider = _PhysicalDisplays(
        PhysicalDisplay(r"\\.\DISPLAY1", (0, 0, 2560, 1440), aliases=("27E1Q",))
    )

    mappings = display_mappings_for_frame(
        frame,
        screens=(screen,),
        physical_provider=provider,
    )

    assert mappings[0].display.name == "27E1Q"
    assert mappings[0].display.physical == (0, 0, 2560, 1440)
```

- [ ] **Step 3: Write geometry fallback and ambiguity tests**

Add:

```python
def test_display_mapping_uses_unique_dpi_aware_geometry_fallback():
    frame = CapturedFrame(Image.new("RGB", (2560, 1440)), origin=(0, 0))
    screen = _Screen("MODEL", QRect(0, 0, 1707, 960), 1.5)
    displays = (
        PhysicalDisplay(r"\\.\DISPLAY1", (0, 0, 2560, 1440)),
        PhysicalDisplay(r"\\.\DISPLAY2", (2560, 0, 4480, 1080)),
    )
    mappings = display_mappings_for_frame(
        frame,
        screens=(screen,),
        physical_provider=_PhysicalDisplays(*displays),
    )
    assert mappings[0].display.physical == (0, 0, 2560, 1440)


def test_display_mapping_rejects_ambiguous_geometry_fallback():
    frame = CapturedFrame(Image.new("RGB", (1920, 1080)), origin=(0, 0))
    screen = _Screen("MODEL", QRect(0, 0, 1920, 1080), 1.0)
    displays = (
        PhysicalDisplay(r"\\.\DISPLAY1", (0, 0, 1920, 1080)),
        PhysicalDisplay(r"\\.\DISPLAY2", (1920, 0, 3840, 1080)),
    )
    with pytest.raises(ValueError, match="无法唯一匹配"):
        display_mappings_for_frame(
            frame,
            screens=(screen,),
            physical_provider=_PhysicalDisplays(*displays),
        )
```

- [ ] **Step 4: Verify RED**

Run:

```powershell
python -m pytest tests/ui/test_display_mapping.py -v
```

Expected: FAIL because `PhysicalDisplay` has no aliases and the matcher still requires exact names.

### Task 5: Add Windows display aliases

**Files:**
- Modify: `flow_runner/infrastructure/windowing/displays.py`
- Modify: `tests/unit/infrastructure/test_displays.py`

- [ ] **Step 1: Extend PhysicalDisplay compatibly**

Change the model to:

```python
@dataclass(frozen=True, slots=True)
class PhysicalDisplay:
    name: str
    rect: Rect
    aliases: tuple[str, ...] = ()
```

- [ ] **Step 2: Add a narrow Windows alias provider**

Implement private helpers using `EnumDisplayDevicesW` and EDID:

- Query the monitor attached to each GDI name such as `\\.\DISPLAY1` and read its device ID,
  for example `MONITOR\HKC2712\...`.
- Enumerate `SYSTEM\CurrentControlSet\Enum\DISPLAY\HKC2712` instances and read each
  `Device Parameters\EDID` value.
- Parse EDID monitor-name descriptor `0xFC` at standard detailed-descriptor offsets and return
  names such as `27E1Q`.
- Normalize aliases case-insensitively, ignore empty values, and preserve the first spelling.
- Registry, device-enumeration, or EDID failures return no aliases and do not fail physical monitor
  enumeration.

- [ ] **Step 3: Attach aliases during EnumDisplayMonitors**

Compute aliases once before monitor enumeration:

```python
aliases = _windows_display_aliases()
```

Construct:

```python
PhysicalDisplay(
    str(info.szDevice),
    (bounds.left, bounds.top, bounds.right, bounds.bottom),
    aliases.get(str(info.szDevice).casefold(), ()),
)
```

- [ ] **Step 4: Unit-test alias normalization without real displays**

Extract the path-to-alias reduction into a pure helper and test:

```python
assert _normalize_display_aliases(
    [(r"\\.\DISPLAY1", "27E1Q"), (r"\\.\display1", "27e1q"), (r"\\.\DISPLAY1", "")]
) == {r"\\.\display1": ("27E1Q",)}
```

- [ ] **Step 5: Verify focused infrastructure tests**

Run:

```powershell
python -m pytest tests/unit/infrastructure/test_displays.py -q
```

Expected: PASS.

### Task 6: Implement one-to-one display matching

**Files:**
- Modify: `flow_runner/ui/display_mapping.py`
- Modify: `tests/ui/test_display_mapping.py`

- [ ] **Step 1: Extend ScreenGeometry**

Add:

```python
def devicePixelRatio(self) -> float: ...
```

- [ ] **Step 2: Implement pure matching helpers**

Create:

```python
def match_display_geometries(
    screens: tuple[ScreenGeometry, ...],
    physical_displays: tuple[PhysicalDisplay, ...],
) -> tuple[DisplayGeometry, ...]:
```

For each screen, excluding already-used physical displays:

1. Build normalized names from `display.name` and `display.aliases`.
2. If exactly one unused display matches `screen.name().casefold()`, use it.
3. Otherwise find unused geometry-compatible displays where:

```python
expected_width = round(screen.geometry().width() * screen.devicePixelRatio())
expected_height = round(screen.geometry().height() * screen.devicePixelRatio())
physical_width = rect[2] - rect[0]
physical_height = rect[3] - rect[1]
abs(expected_width - physical_width) <= 1
abs(expected_height - physical_height) <= 1
```

4. If one candidate remains, use it.
5. If zero or multiple candidates remain, raise a diagnostic `ValueError` containing screen name, logical geometry, DPR, and candidate device names.

Do not reuse a selected physical display.

- [ ] **Step 3: Use the matcher in display_mappings_for_frame**

Replace the direct name dictionary loop with:

```python
geometries = match_display_geometries(qt_screens, provider.displays())
```

Keep `build_display_mappings()` unchanged.

- [ ] **Step 4: Verify all mapping tests**

Run:

```powershell
python -m pytest tests/ui/test_display_mapping.py tests/ui/test_region_capture.py tests/ui/test_point_capture.py -q
```

Expected: PASS.

### Task 7: Exclude hidden Flow Runner windows from capture

**Files:**
- Modify: `flow_runner/ui/application_visibility.py`
- Modify: `tests/ui/test_point_capture.py`

- [ ] **Step 1: Write failing ordering tests**

Verify the selection order is `exclude → hide → DwmFlush → capture → select → restore affinity →
show`, and verify restoration after cancellation and exceptions.

- [ ] **Step 2: Implement Windows capture exclusion**

Use `GetWindowDisplayAffinity` to record each visible top-level window's original value, set
`WDA_EXCLUDEFROMCAPTURE` before hiding, process Qt events, call `DwmFlush()`, and restore the original
affinity while the windows are still hidden. Unsupported APIs safely return an empty saved state.

- [ ] **Step 3: Verify capture tests and repeat real selection**

Run `tests/ui/test_point_capture.py`, `test_capture_preferences.py`, and `test_region_capture.py`, then
repeat point/region selection at least ten times with hiding enabled and confirm no frozen or
translucent Flow Runner image remains.

### Task 8: Integration, documentation, and verification

**Files:**
- Modify: `README.md`
- Verify all changed production and test files.

- [ ] **Step 1: Update README**

Document that step cards show one route per line with numbered group/workflow/step targets and count predicates. Document that region/point selection matches Qt monitor models to Windows device names and uses a guarded DPI-aware geometry fallback.

- [ ] **Step 2: Run focused UI tests**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_route_summaries.py tests/ui/test_simple_shell.py tests/ui/test_step_editors.py tests/ui/test_display_mapping.py tests/ui/test_region_capture.py tests/ui/test_point_capture.py -q
```

Expected: PASS.

- [ ] **Step 3: Run the complete suite**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 4: Run quality gates**

```powershell
python -m ruff check flow_runner tests
python -m ruff format --check flow_runner tests
python -m mypy flow_runner
python -m compileall -q flow_runner
python -m pip check
git diff --check
```

Expected: all commands exit successfully.

- [ ] **Step 5: Review the final diff**

```powershell
git status --short
git diff -- README.md flow_runner/display_labels.py flow_runner/ui/route_summaries.py flow_runner/ui/editors/route_editor.py flow_runner/ui/panels/step_list_panel.py flow_runner/ui/main_window.py flow_runner/infrastructure/windowing/displays.py flow_runner/ui/display_mapping.py tests/unit/test_display_labels.py tests/unit/infrastructure/test_displays.py tests/ui/test_route_summaries.py tests/ui/test_display_mapping.py tests/ui/test_simple_shell.py tests/ui/test_main_window.py
```

Expected: only this feature, tests, and documentation appear; the pre-existing `data/project.json` modification remains untouched.

- [ ] **Step 6: Perform real GUI acceptance**

Launch Flow Runner normally and verify:

1. A step with multiple routes shows one route per line.
2. Jump/call targets and count predicates show numbered group/workflow/step paths.
3. A step without routes describes implicit success/non-success behavior.
4. On monitor `27E1Q`, region selection, template screenshot selection, and point selection open without the previous name-matching error.
5. Selected desktop coordinates and window-relative coordinates match the chosen location.
6. Close without saving test-only changes; confirm `data/project.json` hash is unchanged.

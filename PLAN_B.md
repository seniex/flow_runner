# Flow Runner Plan B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Do not dispatch subagents unless the user explicitly asks for delegation. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the accepted logging and numbering corrections, move all active configuration and generated runtime data into `data/`, safely migrate the real project, and leave the repository with current documentation and no obsolete root-level implementation files.

**Architecture:** Add one pure display-label index and one pure application-path value object, then inject both into the existing UI, logging, persistence, capture, and recording boundaries. Perform the real data relocation through a tested staging migration that copies and validates before any old location is removed; archive historical material separately from active runtime data.

**Tech Stack:** Python 3.12, PySide6, Pydantic 2, pathlib, pytest, pytest-qt, Ruff, mypy.

**Execution status:** Complete. Final verification: 337 passing tests, 155 formatted files, and mypy success across 116 source files. The user confirmed all six real GUI checks on 2026-07-15. Multi-monitor and Tesseract remain `DEFERRED`. The design is approved in `docs/superpowers/specs/2026-07-15-plan-b-project-data-and-cleanup-design.md`.

**Git rule:** Do not commit, merge, push, tag, or publish unless the user explicitly requests it. Replace the commit steps normally used by Superpowers with local verification checkpoints.

---

## Protected Current State

The working branch is `feature-region-picker-dark-ui` and contains accepted but uncommitted work. Do not reset, revert, overwrite, or clean the working tree.

Protect these user data and evidence files until the migration task has copied and validated them:

- `project.json`
- `project.*.bak.json`
- `templates/`
- `recordings/`
- `logs/`
- `config/flow_runner.json`
- `scripts/*.json`
- `scripts/*.png`
- `flowUI.png`
- `BGUI.png`

The user has already accepted:

- UI acceptance items 1–4.
- Wait-action countdown behavior.
- Global hotkeys for start, stop, pause/resume, and record/stop-recording.

Multi-monitor and Tesseract real-environment acceptance are `DEFERRED`, not Plan B blockers.

## Target Runtime Layout

```text
data/
├─ project.json
├─ backups/
├─ templates/
│  └─ legacy/
├─ recordings/
│  └─ legacy/
├─ logs/
└─ legacy/
   ├─ config/
   └─ scripts/
```

## Planned File Boundaries

- Create `flow_runner/display_labels.py`: one project-wide UUID-to-numbered-label index shared by UI and readable logging.
- Create `flow_runner/infrastructure/paths.py`: immutable default/explicit project path layout.
- Create `flow_runner/migration/data_directory.py`: dry-run manifest, resource-path rewrite, staging copy, and validation.
- Create `scripts/migrate_plan_b_data.py`: small CLI entry point for the tested migration service.
- Modify `flow_runner/engine/step_executor.py`: preserve completed condition attempts when cancellation occurs.
- Modify `flow_runner/infrastructure/persistence/project_store.py`: support a dedicated backup directory.
- Modify `flow_runner/app.py`: construct and inject `ApplicationPaths`.
- Modify UI/log formatter files: use `ProjectDisplayIndex` and independent group/workflow/step numbering.
- Modify `.gitignore`: ignore generated data while retaining active/legacy tracked configuration assets.
- Modify `README.md`, `REFACTOR_STATUS.md`, and `REAL_ENVIRONMENT_CHECKLIST.md`: document only current behavior and deferred items.
- Archive completed plans under `docs/archive/` and design images under `docs/assets/ui-references/`.

---

### Task 0: Re-establish the Baseline and Freeze the Migration Inventory

**Files:**
- Read: `AGENTS.md`
- Read: `README.md`
- Read: `docs/superpowers/specs/2026-07-15-plan-b-project-data-and-cleanup-design.md`
- Read: `PLAN_B.md`
- Inspect: entire working tree

- [x] **Step 1: Confirm no Flow Runner process is active**

Run:

```powershell
Get-Process | Where-Object {
    $_.ProcessName -like '*flow*runner*' -or
    $_.MainWindowTitle -like '*自动化流程执行器*'
} | Select-Object Id,ProcessName,MainWindowTitle
```

Expected: no active Flow Runner process. If one is present, stop and ask the user to close it before any migration action.

- [x] **Step 2: Capture the dirty working-tree inventory**

Run:

```powershell
git branch --show-current
git status --short
git diff --stat
git diff --check
```

Expected: branch `feature-region-picker-dark-ui`; accepted uncommitted UI/logging work remains present; `git diff --check` succeeds.

- [x] **Step 3: Record hashes and file inventory without changing files**

Run:

```powershell
Get-FileHash -Algorithm SHA256 -LiteralPath project.json
Get-ChildItem -File -Filter 'project*.json' |
    Get-FileHash -Algorithm SHA256
Get-ChildItem -Recurse -File -LiteralPath logs,templates,recordings,config,scripts |
    Sort-Object FullName |
    Select-Object FullName,Length,LastWriteTime
```

Expected: one activity project, five backups, existing logs, one generated template, current and legacy recordings, legacy config, and script assets are all listed.

- [x] **Step 4: Validate the current project before coding**

Run:

```powershell
python -c "from pathlib import Path; from flow_runner.infrastructure.persistence.project_store import ProjectStore; p=ProjectStore(Path('project.json')).load(); print(len(p.groups), sum(len(g.workflows) for g in p.groups), sum(len(w.steps) for g in p.groups for w in g.workflows)); print(p.validate_references())"
```

Expected: `4 99 159` and `[]`.

- [x] **Step 5: Run the existing automated baseline**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest -q
python -m ruff check flow_runner tests scripts
python -m ruff format --check flow_runner tests scripts
python -m mypy flow_runner
python -m compileall -q flow_runner
python -m pip check
git diff --check
```

Expected: the previous baseline was 323 passing tests; record the fresh count and stop if any current check fails before Plan B changes.

---

### Task 1: Preserve Condition Attempts When a Step Is Cancelled

**Files:**
- Modify: `tests/unit/engine/test_step_executor.py`
- Modify: `flow_runner/engine/step_executor.py:102-201`
- Modify: `tests/unit/infrastructure/test_runtime_logging.py`

- [x] **Step 1: Strengthen the existing cancelled-poll test**

In `test_cancelled_step_returns_cancelled_without_another_attempt`, add:

```python
assert result.condition_attempts == 1
assert result.condition_result is not None
assert result.condition_result.outcome is ConditionOutcome.NO_MATCH
```

- [x] **Step 2: Add a cancellation-before-first-evaluation test**

Add:

```python
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
```

- [x] **Step 3: Run the focused tests and verify RED**

Run:

```powershell
python -m pytest -q tests/unit/engine/test_step_executor.py -k "cancelled_step or cancelled_before_first"
```

Expected: the existing cancelled-poll test fails because `condition_attempts` is currently 0.

- [x] **Step 4: Preserve local condition state at the cancellation boundary**

Wrap the loop inside `_execute_condition_step()` rather than changing the outer action-only cancellation behavior:

```python
async def _execute_condition_step(
    self,
    step: AutomationStep,
    condition: ConditionNode,
) -> StepResult:
    policy = step.condition_policy
    started_at = self.runtime.clock()
    attempt = 0
    last_result: ConditionResult | None = None

    try:
        while True:
            await self.runtime.wait_until_active()
            self.runtime.context.clear_result()
            hook_results, hooks_succeeded = await self._execute_actions(
                policy.before_attempt_actions,
                step.action_policy.max_attempts,
                step.action_policy.retry_interval_seconds,
            )
            if not hooks_succeeded:
                return StepResult(
                    outcome=StepOutcome.FAILURE,
                    action_results=hook_results,
                    error="before-attempt action failed",
                    condition_attempts=attempt,
                )

            attempt += 1
            last_result = await self._evaluate_condition(condition)
            self.runtime.context.result = last_result
            await self.runtime.wait_until_active()

            if last_result.outcome is ConditionOutcome.MATCH:
                action_results, succeeded = await self._execute_actions(
                    step.actions,
                    step.action_policy.max_attempts,
                    step.action_policy.retry_interval_seconds,
                    revalidate_condition=condition,
                )
                return StepResult(
                    outcome=StepOutcome.SUCCESS if succeeded else StepOutcome.FAILURE,
                    condition_result=self.runtime.context.result or last_result,
                    action_results=action_results,
                    condition_attempts=attempt,
                )

            if last_result.outcome is ConditionOutcome.NO_MATCH:
                hook_results, hooks_succeeded = await self._execute_actions(
                    policy.after_no_match_actions,
                    step.action_policy.max_attempts,
                    step.action_policy.retry_interval_seconds,
                )
                if not hooks_succeeded:
                    return StepResult(
                        outcome=StepOutcome.FAILURE,
                        condition_result=last_result,
                        action_results=hook_results,
                        error="after-no-match action failed",
                        condition_attempts=attempt,
                    )
                if policy.mode is ConditionMode.ONCE:
                    return StepResult(
                        outcome=StepOutcome.NOT_MATCHED,
                        condition_result=last_result,
                        action_results=hook_results,
                        condition_attempts=attempt,
                    )
                terminal_outcome = StepOutcome.TIMEOUT
            else:
                terminal_outcome = StepOutcome.FAILURE

            if self._attempts_exhausted(step, attempt) or self._timeout_reached(
                step, started_at
            ):
                return StepResult(
                    outcome=terminal_outcome,
                    condition_result=last_result,
                    condition_attempts=attempt,
                )

            await self.runtime.wait(policy.interval_seconds)
    except Cancelled as error:
        return StepResult(
            outcome=StepOutcome.CANCELLED,
            condition_result=last_result,
            error=str(error),
            condition_attempts=attempt,
        )
```

This is the existing loop body with one new cancellation boundary; do not otherwise change its match, no-match, timeout, hook, or interval behavior.

- [x] **Step 5: Verify GREEN**

Run:

```powershell
python -m pytest -q tests/unit/engine/test_step_executor.py -k "cancel"
python -m pytest -q tests/unit/engine/test_step_executor.py tests/unit/infrastructure/test_runtime_logging.py
```

Expected: all selected tests pass and action-only cancellation remains unchanged.

- [x] **Step 6: Add a formatter regression for cancelled attempts**

Add to `tests/unit/infrastructure/test_runtime_logging.py`:

```python
def test_normal_formatter_reports_preserved_cancelled_condition_attempts():
    project, workflow, step = _project()
    event = RuntimeEvent(
        task_id=uuid4(),
        kind="step.finished",
        state=RunnerState.RUNNING,
        monotonic_timestamp=3.0,
        workflow_id=workflow.id,
        step_id=step.id,
        outcome=StepOutcome.CANCELLED,
        details={"result": {"condition_attempts": 3}},
    )

    line = RuntimeEventFormatter(project).format(event)

    assert "取消" in line
    assert "检测 3 次" in line
```

Run:

```powershell
python -m pytest -q tests/unit/infrastructure/test_runtime_logging.py
```

Expected: all runtime logging unit tests pass.

---

### Task 2: Add Independent Numbered Display Labels

**Files:**
- Create: `flow_runner/display_labels.py`
- Create: `tests/unit/test_display_labels.py`
- Modify: `flow_runner/infrastructure/logging/formatters.py`
- Modify: `tests/unit/infrastructure/test_runtime_logging.py`

- [x] **Step 1: Write the pure display-index tests**

Create `tests/unit/test_display_labels.py`:

```python
from flow_runner.display_labels import ProjectDisplayIndex
from flow_runner.domain.project import AutomationStep, FlowGroup, Project, Workflow


def test_display_numbers_reset_in_each_direct_container():
    first_steps = [AutomationStep(name="A1"), AutomationStep(name="A2")]
    second_steps = [AutomationStep(name="B1")]
    first_workflows = [
        Workflow(name="流程A", steps=first_steps),
        Workflow(name="流程B", steps=second_steps),
    ]
    second_workflow = Workflow(name="流程C", steps=[AutomationStep(name="C1")])
    project = Project(
        name="p",
        groups=[
            FlowGroup(name="组A", workflows=first_workflows),
            FlowGroup(name="组B", workflows=[second_workflow]),
        ],
    )

    labels = ProjectDisplayIndex(project)

    assert labels.group_label(project.groups[0].id) == "01. 组A"
    assert labels.group_label(project.groups[1].id) == "02. 组B"
    assert labels.workflow_label(first_workflows[1].id) == "02. 流程B"
    assert labels.workflow_label(second_workflow.id) == "01. 流程C"
    assert labels.step_label(first_steps[1].id) == "02. A2"
    assert labels.step_label(second_steps[0].id) == "01. B1"
    assert labels.step_path(first_steps[1].id) == "01. 组A / 01. 流程A / 02. A2"


def test_display_numbers_are_not_written_into_model_names():
    step = AutomationStep(name="原步骤")
    workflow = Workflow(name="原流程", steps=[step])
    group = FlowGroup(name="原组", workflows=[workflow])
    project = Project(name="p", groups=[group])

    ProjectDisplayIndex(project)

    assert group.name == "原组"
    assert workflow.name == "原流程"
    assert step.name == "原步骤"
```

- [x] **Step 2: Run the tests and verify RED**

Run:

```powershell
python -m pytest -q tests/unit/test_display_labels.py
```

Expected: collection fails because `flow_runner.display_labels` does not exist.

- [x] **Step 3: Implement the complete display index**

Create `flow_runner/display_labels.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from flow_runner.domain.project import Project


@dataclass(frozen=True, slots=True)
class NumberedName:
    index: int
    name: str

    @property
    def label(self) -> str:
        return f"{self.index:02d}. {self.name}"


class ProjectDisplayIndex:
    def __init__(self, project: Project) -> None:
        self._groups: dict[UUID, NumberedName] = {}
        self._workflows: dict[UUID, NumberedName] = {}
        self._steps: dict[UUID, NumberedName] = {}
        self._workflow_groups: dict[UUID, UUID] = {}
        self._step_workflows: dict[UUID, UUID] = {}
        for group_index, group in enumerate(project.groups, start=1):
            self._groups[group.id] = NumberedName(group_index, group.name)
            for workflow_index, workflow in enumerate(group.workflows, start=1):
                self._workflows[workflow.id] = NumberedName(workflow_index, workflow.name)
                self._workflow_groups[workflow.id] = group.id
                for step_index, step in enumerate(workflow.steps, start=1):
                    self._steps[step.id] = NumberedName(step_index, step.name)
                    self._step_workflows[step.id] = workflow.id

    def group_label(self, group_id: UUID) -> str:
        item = self._groups.get(group_id)
        return item.label if item is not None else "未知流程组"

    def workflow_label(self, workflow_id: UUID) -> str:
        item = self._workflows.get(workflow_id)
        return item.label if item is not None else "未知流程"

    def step_label(self, step_id: UUID) -> str:
        item = self._steps.get(step_id)
        return item.label if item is not None else "未知步骤"

    def workflow_path(self, workflow_id: UUID) -> str:
        group_id = self._workflow_groups.get(workflow_id)
        if group_id is None:
            return self.workflow_label(workflow_id)
        return f"{self.group_label(group_id)} / {self.workflow_label(workflow_id)}"

    def step_path(self, step_id: UUID) -> str:
        workflow_id = self._step_workflows.get(step_id)
        if workflow_id is None:
            return self.step_label(step_id)
        return f"{self.workflow_path(workflow_id)} / {self.step_label(step_id)}"

    def workflow_id_for_step(self, step_id: UUID) -> UUID | None:
        return self._step_workflows.get(step_id)
```

- [x] **Step 4: Verify the pure index GREEN**

Run:

```powershell
python -m pytest -q tests/unit/test_display_labels.py
```

Expected: 2 tests pass.

- [x] **Step 5: Replace formatter-local name maps with `ProjectDisplayIndex`**

In `RuntimeEventFormatter.set_project()`:

```python
def set_project(self, project: Project) -> None:
    self._labels = ProjectDisplayIndex(project)
```

Replace `_location()` with:

```python
def _location(self, workflow_id: UUID | None, step_id: UUID | None) -> str:
    if step_id is not None:
        return self._labels.step_path(step_id)
    if workflow_id is not None:
        return self._labels.workflow_path(workflow_id)
    return ""
```

In `_route_target()`, resolve next-step and workflow routes through `step_path()` and `workflow_path()`.

- [x] **Step 6: Update formatter expectations and verify**

Change readable path assertions to include independent prefixes:

```python
assert "01. 组A / 01. 流程一 / 01. 等待加载" in normal
assert "路由 → 01. 组A / 01. 流程一 / 02. 下一步" in line
```

Run:

```powershell
python -m pytest -q tests/unit/test_display_labels.py tests/unit/infrastructure/test_runtime_logging.py tests/ui/test_runtime_log.py
```

Expected: all selected tests pass.

---

### Task 3: Apply Independent Numbers to the Qt UI

**Files:**
- Modify: `flow_runner/ui/panels/flow_tree_panel.py`
- Modify: `flow_runner/ui/panels/step_list_panel.py`
- Modify: `flow_runner/ui/main_window.py`
- Modify: `flow_runner/ui/editors/route_editor.py`
- Modify: `flow_runner/ui/dialogs/guided_add_dialog.py`
- Modify: `flow_runner/ui/dialogs/template_step_dialog.py`
- Modify: `flow_runner/ui/dialogs/parallel_block_dialog.py`
- Modify: `tests/ui/test_simple_shell.py`
- Modify: `tests/ui/test_main_window.py`
- Modify: `tests/ui/test_step_editors.py`
- Modify: `tests/ui/test_step_templates.py`

- [x] **Step 1: Write tree, startup-selector, and step-card failing tests**

Add these exact assertions to fixtures containing `组A / 流程一 / 步骤一`:

```python
assert window.flow_tree.tree.topLevelItem(0).text(0) == "01. 组A"
assert window.flow_tree.tree.topLevelItem(0).child(0).text(0) == "01. 流程一"
assert window.startup_group_combo.itemText(0) == "01. 组A"
assert window.startup_workflow_combo.itemText(0) == "01. 流程一"

first_item = window.step_list.list.item(0)
first_card = window.step_list.list.itemWidget(first_item)
assert first_card.number_label.text() == "01."
assert first_card.title_label.text() == "步骤一"
window.step_list.select_step(first_step.id)
assert first_card.number_label.isVisible()
assert first_card.title_label.isHidden()
```

- [x] **Step 2: Write route/dialog label failing tests**

Assert labels use independent numbering:

```python
assert route_editor.workflow_combo.itemText(0) == "01. 组A / 01. 流程一"
assert route_editor.predicate_step_combo.itemText(1).endswith("/ 02. 步骤二")
assert dialog.control_workflow_combo.itemText(0) == "01. 组A / 01. 流程一"
assert template_dialog.target_step_combo.itemText(0) == "01. 步骤一"
assert parallel_dialog.workflow_list.item(0).text() == "01. 组A / 01. 流程一"
```

- [x] **Step 3: Run the UI tests and verify RED**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest -q tests/ui/test_simple_shell.py tests/ui/test_main_window.py tests/ui/test_step_editors.py tests/ui/test_step_templates.py -k "number or label or card or route or template or parallel"
```

Expected: current labels contain raw names and `StepCardWidget` has no persistent `number_label`.

- [x] **Step 4: Number the flow tree and startup selectors**

Construct `ProjectDisplayIndex(project)` in each refresh method and use:

```python
group_item = QTreeWidgetItem([labels.group_label(group.id)])
item = QTreeWidgetItem([labels.workflow_label(workflow.id)])
```

In `MainWindow._refresh_startup_selectors()` and `_populate_startup_workflows()` use:

```python
self.startup_group_combo.addItem(labels.group_label(group.id), group.id)
self.startup_workflow_combo.addItem(labels.workflow_label(workflow.id), workflow.id)
```

Keep combo data as UUIDs and keep rename dialogs on raw `.name` values.

- [x] **Step 5: Keep the step number visible in both card states**

Change the card constructor to `StepCardWidget(step: AutomationStep, index: int)` and create:

```python
self.number_label = QLabel(f"{index:02d}.")
self.number_label.setObjectName("stepCardNumber")
self.title_label = QLabel(step.name)

header = QWidget()
header_layout = QHBoxLayout(header)
header_layout.setContentsMargins(0, 0, 0, 0)
header_layout.setSpacing(6)
header_layout.addWidget(self.number_label)
header_layout.addWidget(self.title_label, 1)
```

Add `header` before the body. `set_expanded()` must continue hiding only `title_label`; it must never hide `number_label`. In `set_workflow()` enumerate with `start=1`:

```python
for index, step in enumerate(workflow.steps, start=1):
    card = StepCardWidget(step, index)
```

- [x] **Step 6: Number all readable target selectors and summaries**

In each editor/dialog, create one `ProjectDisplayIndex(project)` and use:

```python
workflow_path = labels.workflow_path(workflow.id)
step_label = labels.step_label(step.id)
step_path = labels.step_path(step.id)
```

Use `workflow_path` for workflow selectors, `step_label` for selectors already scoped to one workflow, and `step_path` for global step selectors and route summaries. Do not change UUID item data.

- [x] **Step 7: Verify UI GREEN**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest -q tests/ui/test_simple_shell.py tests/ui/test_main_window.py tests/ui/test_step_editors.py tests/ui/test_step_templates.py tests/ui/test_runtime_log.py
```

Expected: all selected tests pass; no hierarchical `1.2.1` string appears.

- [x] **Step 8: Audit all remaining raw-name display sites**

Run:

```powershell
rg -n "addItem\(.*\.name|QTreeWidgetItem\(\[.*\.name|group\.name.*workflow\.name|step\.name" flow_runner/ui flow_runner/infrastructure/logging
```

Expected: remaining raw names are limited to editing, confirmation, model construction, and accessibility text. Any selector/list/log display site must use `ProjectDisplayIndex`.

---

### Task 4: Define the Central Application Path Layout

**Files:**
- Create: `flow_runner/infrastructure/paths.py`
- Create: `tests/unit/infrastructure/test_application_paths.py`

- [x] **Step 1: Write failing default and explicit path tests**

Create:

```python
from pathlib import Path

from flow_runner.infrastructure.paths import ApplicationPaths


def test_default_paths_put_all_runtime_data_under_data(tmp_path):
    paths = ApplicationPaths.default(tmp_path / "flow_runner")

    assert paths.project_file == tmp_path / "flow_runner" / "data" / "project.json"
    assert paths.backup_directory == tmp_path / "flow_runner" / "data" / "backups"
    assert paths.template_directory == tmp_path / "flow_runner" / "data" / "templates"
    assert paths.recording_directory == tmp_path / "flow_runner" / "data" / "recordings"
    assert paths.latest_recording_file == paths.recording_directory / "latest.json"
    assert paths.log_directory == tmp_path / "flow_runner" / "data" / "logs"
    assert paths.session_name == "flow_runner"


def test_explicit_project_keeps_test_data_beside_that_project(tmp_path):
    project_file = tmp_path / "custom" / "project.json"

    paths = ApplicationPaths.for_project(project_file)

    assert paths.project_file == project_file
    assert paths.backup_directory == project_file.parent / "backups"
    assert paths.template_directory == project_file.parent / "templates"
    assert paths.recording_directory == project_file.parent / "recordings"
    assert paths.log_directory == project_file.parent / "logs"
    assert paths.session_name == "custom"
```

- [x] **Step 2: Verify RED**

Run:

```powershell
python -m pytest -q tests/unit/infrastructure/test_application_paths.py
```

Expected: import failure because the module does not exist.

- [x] **Step 3: Implement `ApplicationPaths`**

Create:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ApplicationPaths:
    application_root: Path
    data_directory: Path
    project_file: Path
    backup_directory: Path
    template_directory: Path
    recording_directory: Path
    log_directory: Path

    @classmethod
    def default(cls, application_root: Path) -> ApplicationPaths:
        root = application_root.resolve()
        data = root / "data"
        return cls._build(root, data, data / "project.json")

    @classmethod
    def for_project(cls, project_file: Path) -> ApplicationPaths:
        project = project_file.resolve()
        data = project.parent
        return cls._build(data, data, project)

    @classmethod
    def _build(
        cls,
        application_root: Path,
        data_directory: Path,
        project_file: Path,
    ) -> ApplicationPaths:
        return cls(
            application_root=application_root,
            data_directory=data_directory,
            project_file=project_file,
            backup_directory=data_directory / "backups",
            template_directory=data_directory / "templates",
            recording_directory=data_directory / "recordings",
            log_directory=data_directory / "logs",
        )

    @property
    def latest_recording_file(self) -> Path:
        return self.recording_directory / "latest.json"

    @property
    def legacy_directory(self) -> Path:
        return self.data_directory / "legacy"

    @property
    def session_name(self) -> str:
        return self.application_root.name or "flow_runner"
```

- [x] **Step 4: Verify GREEN**

Run:

```powershell
python -m pytest -q tests/unit/infrastructure/test_application_paths.py
```

Expected: 2 tests pass.

---

### Task 5: Move Project Backups into a Dedicated Directory

**Files:**
- Modify: `flow_runner/infrastructure/persistence/project_store.py`
- Modify: `tests/integration/test_project_store.py`

- [x] **Step 1: Write the dedicated-backup-directory failing test**

Add:

```python
def test_project_store_writes_and_trims_backups_in_dedicated_directory(tmp_path):
    project_file = tmp_path / "data" / "project.json"
    backup_directory = tmp_path / "data" / "backups"
    store = ProjectStore(project_file, backup_limit=2, backup_directory=backup_directory)

    store.save(Project(name="one"))
    store.save(Project(name="two"))
    store.save(Project(name="three"))
    store.save(Project(name="four"))

    backups = sorted(backup_directory.glob("project.*.bak.json"))
    assert len(backups) == 2
    assert not list(project_file.parent.glob("project.*.bak.json"))
```

- [x] **Step 2: Verify RED**

Run:

```powershell
python -m pytest -q tests/integration/test_project_store.py -k "dedicated_directory"
```

Expected: constructor rejects `backup_directory`.

- [x] **Step 3: Add the optional backup directory**

Update the constructor:

```python
def __init__(
    self,
    path: Path,
    backup_limit: int = 5,
    backup_directory: Path | None = None,
) -> None:
    self.path = path
    self.backup_limit = backup_limit
    self.backup_directory = backup_directory or path.parent
```

Before copying a backup:

```python
self.backup_directory.mkdir(parents=True, exist_ok=True)
backup = self.backup_directory / f"{self.path.stem}.{time.time_ns()}.bak{self.path.suffix}"
```

Trim only:

```python
self.backup_directory.glob(f"{self.path.stem}.*.bak{self.path.suffix}")
```

- [x] **Step 4: Verify GREEN and existing atomic-save behavior**

Run:

```powershell
python -m pytest -q tests/integration/test_project_store.py
```

Expected: all project-store tests pass, including corruption recovery and atomic replacement tests.

---

### Task 6: Inject Paths into Application, Capture, Recording, and Logging

**Files:**
- Modify: `flow_runner/app.py`
- Modify: `flow_runner/ui/region_capture.py`
- Modify: `flow_runner/infrastructure/logging/session.py`
- Modify: `tests/ui/test_app_smoke.py`
- Modify: `tests/ui/test_region_capture.py`
- Modify: `tests/unit/infrastructure/test_runtime_logging.py`
- Modify: `README.md`

- [x] **Step 1: Write failing application composition path tests**

Add an explicit-project test that asserts:

```python
composition = create_application([], project_path=project_file)

assert composition.store.path == project_file
assert composition.store.backup_directory == project_file.parent / "backups"
assert composition.recording_path == project_file.parent / "recordings" / "latest.json"
assert len(list((project_file.parent / "logs").glob("custom_*_normal.log"))) == 1
```

Add a default-path unit test by monkeypatching `Path.cwd()` or by testing `ApplicationPaths.default()` directly; do not create a real root `data/project.json` during UI tests.

- [x] **Step 2: Update region-capture tests to require an explicit template directory**

Construct:

```python
service = RegionCaptureService(
    frame_provider,
    selector=selector,
    template_directory=tmp_path / "data" / "templates",
    now=lambda: fixed_time,
)
```

Assert the PNG is written directly beneath that directory.

- [x] **Step 3: Verify RED**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest -q tests/ui/test_app_smoke.py tests/ui/test_region_capture.py -k "log_file or recording or template or path"
```

Expected: current application uses sibling directories and `RegionCaptureService` expects `project_directory`.

- [x] **Step 4: Construct `ApplicationPaths` once in `create_application()`**

Use:

```python
paths = (
    ApplicationPaths.for_project(project_path)
    if project_path is not None
    else ApplicationPaths.default(Path.cwd())
)
path = paths.project_file
store = ProjectStore(path, backup_directory=paths.backup_directory)
```

Then wire:

```python
log_path = session_log_path(
    paths.log_directory,
    paths.session_name,
    datetime.now(),
    debug=debug_logging,
)

region_capture=RegionCaptureService(
    lambda target: _capture_frame_for_ui(capture, target),
    template_directory=paths.template_directory,
)

recording_path=recording_path or paths.latest_recording_file
```

Pass `paths.application_root` to `_build_ocr_provider()` so default relative third-party paths remain rooted at the repository rather than inside `data/`.

- [x] **Step 5: Change `RegionCaptureService` to own only its output directory**

Replace `_project_directory` and its property with:

```python
self._template_directory = template_directory

@property
def template_directory(self) -> Path:
    return self._template_directory
```

In `capture_template()`:

```python
directory = self._template_directory
directory.mkdir(parents=True, exist_ok=True)
```

- [x] **Step 6: Verify log naming uses the directory/application name**

Update the application smoke expectations from internal `Project.name` values to explicit directory labels. For a project at `tmp_path / "custom" / "project.json"`, assert:

```python
assert len(list((project_file.parent / "logs").glob("custom_*_normal.log"))) == 1
```

Keep the pure `session_log_path()` sanitization and collision tests.

- [x] **Step 7: Verify GREEN**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest -q tests/unit/infrastructure/test_application_paths.py tests/unit/infrastructure/test_runtime_logging.py tests/integration/test_project_store.py tests/ui/test_app_smoke.py tests/ui/test_region_capture.py
```

Expected: all selected tests pass and no test writes outside its `tmp_path`.

- [x] **Step 8: Update the README runtime path contract**

Document these exact defaults:

```text
data/project.json
data/backups/
data/templates/
data/recordings/
data/logs/
```

State that an explicitly supplied `project_path` keeps its auxiliary directories beside that project file.

---

### Task 7: Build a Dry-Run-First Data Migration Service

**Files:**
- Create: `flow_runner/migration/data_directory.py`
- Create: `scripts/migrate_plan_b_data.py`
- Create: `tests/unit/migration/test_data_directory.py`

- [x] **Step 1: Write migration-plan and path-rewrite failing tests**

Create a fixture containing a project with:

```python
condition={
    "id": "image",
    "capability": "vision.image",
    "config": {"template_path": "scripts\\target.png"},
}
actions=[
    ActionSpec(
        capability="recording.playback",
        config={"path": "recordings\\legacy\\play.json"},
    )
]
```

Create the source files and assert the dry-run plan maps them to:

```python
root / "data" / "templates" / "legacy" / "target.png"
root / "data" / "recordings" / "legacy" / "play.json"
```

Assert the migrated project preserves IDs, names, routes, and settings while changing only those path strings.

- [x] **Step 2: Write staging-failure safety tests**

Add a test that injects a copy failure and asserts:

```python
assert (root / "project.json").exists()
assert not (root / "data" / "project.json").exists()
assert not (root / ".plan_b_migration_staging").exists()
```

- [x] **Step 3: Verify RED**

Run:

```powershell
python -m pytest -q tests/unit/migration/test_data_directory.py
```

Expected: import failure because the migration module does not exist.

- [x] **Step 4: Implement immutable migration entries and plan**

Create these public types:

```python
@dataclass(frozen=True, slots=True)
class MigrationEntry:
    source: Path
    destination: Path
    category: str


@dataclass(frozen=True, slots=True)
class DataDirectoryMigrationPlan:
    root: Path
    staging_directory: Path
    data_directory: Path
    entries: tuple[MigrationEntry, ...]
    resource_targets: dict[Path, Path]
```

`build_migration_plan(root)` must enumerate:

- root `project.json`.
- root `project.*.bak.json`.
- every file under `logs/`, `templates/`, and `recordings/`.
- `scripts/转职挑战.png` and `scripts/存档.png` as active legacy templates when present.
- `config/flow_runner.json` and legacy script JSON files as archive entries.

Populate `resource_targets` for every file copied from root `templates/`, every file copied from
root `recordings/`, and the two active `scripts/*.png` templates. Do not add logs, backups, legacy
config, or archived script JSON files to `resource_targets` because project capability configs do
not reference those archive-only files.

Abort if `data/` or `.plan_b_migration_staging/` already exists.

- [x] **Step 5: Implement known-capability resource rewriting**

Use exact capability boundaries:

```python
def rewrite_condition(node: ConditionNode, targets: dict[Path, Path], root: Path) -> ConditionNode:
    if isinstance(node, ConditionGroup):
        return node.model_copy(
            update={"children": [rewrite_condition(child, targets, root) for child in node.children]}
        )
    if node.capability != "vision.image":
        return node
    config = dict(node.config)
    config["template_path"] = rewritten_resource_path(config["template_path"], targets, root)
    return node.model_copy(update={"config": config})


def rewrite_actions(
    actions: list[ActionSpec],
    targets: dict[Path, Path],
    root: Path,
) -> list[ActionSpec]:
    rewritten: list[ActionSpec] = []
    for action in actions:
        if action.capability != "recording.playback":
            rewritten.append(action)
            continue
        config = dict(action.config)
        config["path"] = rewritten_resource_path(config["path"], targets, root)
        rewritten.append(action.model_copy(update={"config": config}))
    return rewritten
```

Apply `rewrite_actions()` to the main step actions and both condition-policy hook action lists with:

```python
def rewrite_step(
    step: AutomationStep,
    targets: dict[Path, Path],
    root: Path,
) -> AutomationStep:
    condition = (
        rewrite_condition(step.condition, targets, root)
        if step.condition is not None
        else None
    )
    condition_policy = step.condition_policy.model_copy(
        update={
            "before_attempt_actions": rewrite_actions(
                step.condition_policy.before_attempt_actions,
                targets,
                root,
            ),
            "after_no_match_actions": rewrite_actions(
                step.condition_policy.after_no_match_actions,
                targets,
                root,
            ),
        }
    )
    return step.model_copy(
        update={
            "condition": condition,
            "actions": rewrite_actions(step.actions, targets, root),
            "condition_policy": condition_policy,
        }
    )


def rewrite_project_resources(
    project: Project,
    targets: dict[Path, Path],
    root: Path,
) -> Project:
    groups = [
        group.model_copy(
            update={
                "workflows": [
                    workflow.model_copy(
                        update={
                            "steps": [
                                rewrite_step(step, targets, root)
                                for step in workflow.steps
                            ]
                        }
                    )
                    for workflow in group.workflows
                ]
            }
        )
        for group in project.groups
    ]
    return project.model_copy(update={"groups": groups})
```

These copies retain every existing UUID, route, setting, action policy, and parallel block.

`rewritten_resource_path()` must resolve a relative source against `root`, compare resolved `Path` objects, and return the absolute target string only when that source has an explicit migration target. Leave unrelated external Python programs and PaddleOCR paths unchanged.

- [x] **Step 6: Implement staged execution without deleting sources**

`execute_migration(plan)` must:

1. Create `.plan_b_migration_staging/data/`.
2. Copy every entry to its staging-relative target using `shutil.copy2`.
3. Load and rewrite the copied project.
4. Save the rewritten project directly as staging `data/project.json`.
5. Validate `Project.validate_references()`.
6. Validate every migrated image-template and recording-playback file exists.
7. Move the completed staging `data/` to root `data/`.
8. Remove the now-empty staging directory.

Do not delete or move any source file in this function.

- [x] **Step 7: Add the CLI with explicit dry-run/apply modes**

Create `scripts/migrate_plan_b_data.py`:

```python
from __future__ import annotations

import argparse
from pathlib import Path

from flow_runner.migration.data_directory import build_migration_plan, execute_migration


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    plan = build_migration_plan(args.root)
    for entry in plan.entries:
        print(f"{entry.category}: {entry.source} -> {entry.destination}")
    if not args.apply:
        print("DRY RUN: no files changed")
        return 0
    execute_migration(plan)
    print(f"MIGRATED: {plan.data_directory}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 8: Verify GREEN**

Run:

```powershell
python -m pytest -q tests/unit/migration/test_data_directory.py tests/unit/migration/test_legacy.py
python -m ruff check flow_runner/migration/data_directory.py scripts/migrate_plan_b_data.py tests/unit/migration/test_data_directory.py
python -m mypy flow_runner/migration/data_directory.py
```

Expected: all selected tests and static checks pass.

---

### Task 8: Dry-Run and Apply the Real Data Migration

**Files:**
- Create during execution: `data/`
- Preserve until post-validation: all root data listed in “Protected Current State”

- [x] **Step 1: Run the real dry-run manifest**

Run:

```powershell
python scripts/migrate_plan_b_data.py --root .
```

Expected: every source and destination is printed, the final line is `DRY RUN: no files changed`, and `data/` does not yet exist.

- [x] **Step 2: Compare the dry-run manifest with actual project references**

Run:

```powershell
Select-String -LiteralPath project.json -Pattern '"path"','"template_path"' |
    Select-Object LineNumber,Line
```

Confirm the manifest includes all three legacy recordings, both referenced script PNGs, and the generated template. Stop if a referenced local file has no migration target.

- [x] **Step 3: Present the manifest summary before the real write**

Report counts for activity config, backups, logs, templates, recordings, and archived legacy inputs. The user has approved Plan B, but this checkpoint must still state that the next command creates `data/` from real business files.

- [x] **Step 4: Apply the migration**

Run:

```powershell
python scripts/migrate_plan_b_data.py --root . --apply
```

Expected: `data/project.json` and all target subdirectories exist; every old source still exists because source cleanup is a later task.

- [x] **Step 5: Validate the migrated project and resources**

Run:

```powershell
python -c "from pathlib import Path; from flow_runner.infrastructure.persistence.project_store import ProjectStore; p=ProjectStore(Path('data/project.json'), backup_directory=Path('data/backups')).load(); print(len(p.groups), sum(len(g.workflows) for g in p.groups), sum(len(w.steps) for g in p.groups for w in g.workflows)); print(p.validate_references())"
Get-ChildItem -Recurse -File -LiteralPath data |
    Sort-Object FullName |
    Select-Object FullName,Length
```

Expected: `4 99 159`, `[]`, and all migrated files are present.

- [x] **Step 6: Compare project semantics excluding mapped resource strings**

Use the migration test helper to normalize known resource paths in both old and new projects, then assert their `model_dump(mode="json")` values are equal. Do not accept a comparison that ignores IDs, routes, settings, policies, or actions.

- [x] **Step 7: Launch only an offscreen composition smoke test against the migrated project**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest -q tests/ui/test_app_smoke.py -k "creates or loads or log_file"
```

Expected: tests pass. Do not start the real GUI or execute automation in this task.

---

### Task 9: Switch the Repository to the New Data Layout and Clean Old Locations

**Files:**
- Modify: `.gitignore`
- Remove after validation: root `project.json`, root `project.*.bak.json`, root `logs/`, root `templates/`, root `recordings/`, `config/flow_runner.json`, archived `scripts/*.json`, migrated `scripts/*.png`
- Remove after final reference search: `flow_runner_p1.py`, `flow_runner_p2.py`, `flow_runner_p3.py`
- Preserve: `scripts/preview_dark_ui.py`

- [x] **Step 1: Add granular generated-data ignore rules**

Update `.gitignore` with:

```gitignore
# Flow Runner active runtime data
data/backups/
data/logs/
data/templates/*
!data/templates/legacy/
!data/templates/legacy/*.png
data/recordings/latest.json
```

Do not ignore `data/project.json`, `data/legacy/`, `data/recordings/legacy/`, or `data/templates/legacy/`.

- [x] **Step 2: Prove historical Python files are unreferenced**

Run:

```powershell
rg -n "flow_runner_p1|flow_runner_p2|flow_runner_p3" . -g '!flow_runner_p1.py' -g '!flow_runner_p2.py' -g '!flow_runner_p3.py' -g '!PaddleOCR-json_v*/**'
```

Expected: no references. If a reference appears, update the plan before deleting those files.

Actual audit: references were limited to historical/design documentation and the cleanup plan;
there were no imports or runtime configuration references. The README current-state statement was
updated before deletion, while historical documents retain their original references for archive.

- [x] **Step 3: Remove only the confirmed obsolete Python implementations**

Use `apply_patch` to delete:

```text
flow_runner_p1.py
flow_runner_p2.py
flow_runner_p3.py
```

Do not delete current package modules under `flow_runner/`.

- [x] **Step 4: Remove old activity-data locations only after new-data validation**

Before each removal, resolve and print both old and new absolute paths and confirm they are inside the repository root. Then use native PowerShell `Remove-Item -LiteralPath` on the exact old files/directories only.

Remove:

```text
project.json
project.*.bak.json
logs/
templates/
recordings/
config/flow_runner.json
scripts/亮屏.json
scripts/基本卡片.json
scripts/最小化.json
scripts/退出游戏.json
scripts/存档.png
scripts/转职挑战.png
```

Expected: `data/` copies remain intact and `scripts/preview_dark_ui.py` remains.

- [x] **Step 5: Remove empty legacy directories**

Remove `config/` only if it is empty. Keep `scripts/` because it still contains the dark UI preview script.

- [x] **Step 6: Clear only reproducible tool caches**

Resolve and verify these directories are exactly under the repository root, then remove them with native PowerShell:

```text
.pytest_cache/
.mypy_cache/
.ruff_cache/
```

Do not remove `.superpowers/`, `.worktrees/`, `.git/`, or `PaddleOCR-json_v1.4.1/`.

- [x] **Step 7: Verify no root runtime artifacts remain**

Run:

```powershell
Get-ChildItem -Force | Select-Object Mode,Name
Get-ChildItem -File -Filter 'project*.json'
Test-Path -LiteralPath logs
Test-Path -LiteralPath templates
Test-Path -LiteralPath recordings
```

Expected: no root project JSON/backup files and the three old runtime directories return `False`; `data/` exists.

---

### Task 10: Archive Completed Plans and Design References

**Files:**
- Create: `docs/archive/`
- Create: `docs/assets/ui-references/`
- Move: `FLOW_RUNNER_QT_REFACTOR_DESIGN.md`
- Move: `FLOW_RUNNER_QT_REFACTOR_IMPLEMENTATION_PLAN.md`
- Move: `SAVE_EDITOR_FIX_PLAN.md`
- Move: `IMPROVEMENT_A_PLAN.md`
- Move: `LEGACY_CONVERSION_REPORT.md`
- Move: `flowUI.png`
- Move: `BGUI.png`
- Modify links in: `README.md`, `REFACTOR_STATUS.md`, `REAL_ENVIRONMENT_CHECKLIST.md`, `PLAN_B.md`

- [x] **Step 1: Create archive and asset destinations**

Create:

```text
docs/archive/
docs/assets/ui-references/
```

- [x] **Step 2: Move completed documents without rewriting their history**

Move to `docs/archive/` with the same filenames:

```text
FLOW_RUNNER_QT_REFACTOR_DESIGN.md
FLOW_RUNNER_QT_REFACTOR_IMPLEMENTATION_PLAN.md
SAVE_EDITOR_FIX_PLAN.md
IMPROVEMENT_A_PLAN.md
LEGACY_CONVERSION_REPORT.md
```

Use repository-local moves; do not recreate these large files with changed line endings.

- [x] **Step 3: Move UI references**

Move:

```text
flowUI.png -> docs/assets/ui-references/flowUI.png
BGUI.png -> docs/assets/ui-references/BGUI.png
```

- [x] **Step 4: Repair documentation links**

Run:

```powershell
rg -n "FLOW_RUNNER_QT_REFACTOR|SAVE_EDITOR_FIX_PLAN|IMPROVEMENT_A_PLAN|LEGACY_CONVERSION_REPORT|flowUI\.png|BGUI\.png" . -g '*.md'
```

Update each live-document link to the new path. Archived documents may refer to their historical root locations in prose, but active links must resolve.

- [x] **Step 5: Verify root-document scope**

Expected root documentation after cleanup:

```text
AGENTS.md
PLAN_B.md
README.md
REAL_ENVIRONMENT_CHECKLIST.md
REFACTOR_STATUS.md
```

`pyproject.toml` and `.editorconfig` remain root configuration files because they configure development tooling rather than Flow Runner runtime data.

---

### Task 11: Consolidate Current Status and Deferred Acceptance

**Files:**
- Modify: `README.md`
- Modify: `REFACTOR_STATUS.md`
- Modify: `REAL_ENVIRONMENT_CHECKLIST.md`
- Modify: `PLAN_B.md` checkboxes/status as work completes

- [x] **Step 1: Rewrite `REFACTOR_STATUS.md` as a current summary**

Keep these sections only:

```markdown
# Flow Runner Qt Current Status

## Current architecture
## Completed functionality
## Latest automated verification
## Real-environment acceptance
## Deferred acceptance
## Active runtime data layout
## Remaining Plan B checks
```

Record the accepted UI/logging/countdown work, the new `data/` layout, and the fresh test count. Remove stale statements that global hotkeys remain blocked.

- [x] **Step 2: Update the real-environment status vocabulary**

At the top of `REAL_ENVIRONMENT_CHECKLIST.md`, define:

```text
PASS: actually tested and passed.
FAIL: actually tested and failed.
BLOCKED: intended for current execution but cannot proceed because a prerequisite is unavailable.
DEFERRED: intentionally postponed by the user and not a current completion blocker.
```

- [x] **Step 3: Record global hotkeys as PASS**

Use the exact evidence:

```text
PASS（2026-07-15，用户实测）：启动、停止、暂停/继续、录制/停止录制均成功；未观察到重复触发。
```

Do not claim Codex generated the physical key events.

- [x] **Step 4: Mark multi-monitor and Tesseract as DEFERRED**

Preserve their existing environment evidence and replace the current result label with `DEFERRED`. State that the user explicitly postponed both on 2026-07-15.

- [x] **Step 5: Update README paths and project organization**

Document:

- Default project: `data/project.json`.
- Backups: `data/backups/`.
- Generated template screenshots: `data/templates/`.
- Recordings: `data/recordings/`.
- Logs: `data/logs/`.
- Independent display numbers for groups, workflows, and steps.
- Raw names and UUIDs remain unchanged.

- [x] **Step 6: Check documentation consistency**

Run:

```powershell
rg -n "root.*project\.json|根目录.*project\.json|recordings/latest\.json|templates/|logs/|全局热键.*BLOCKED|多显示器.*BLOCKED|Tesseract.*BLOCKED" README.md REFACTOR_STATUS.md REAL_ENVIRONMENT_CHECKLIST.md PLAN_B.md
```

Expected: any matches are historical explanation or migration instructions, not stale current-state claims.

---

### Task 12: Full Verification and Final Manual Handoff

**Files:**
- Review: entire final diff and untracked data layout
- Update: `PLAN_B.md` execution status and actual verification counts

- [x] **Step 1: Validate the activity project and every local resource**

Run:

```powershell
python -c "from pathlib import Path; from flow_runner.infrastructure.persistence.project_store import ProjectStore; p=ProjectStore(Path('data/project.json'), backup_directory=Path('data/backups')).load(); print(p.validate_references())"
python -c "from pathlib import Path; print(Path('data/project.json').is_file()); print(Path('data/templates').is_dir()); print(Path('data/recordings').is_dir()); print(Path('data/logs').is_dir())"
```

Expected: `[]` and four `True` values.

- [x] **Step 2: Validate a debug log structurally**

Use the latest debug file available under `data/logs/`:

```powershell
python -c "from pathlib import Path; from flow_runner.infrastructure.logging.events import RuntimeEvent; p=sorted(Path('data/logs').glob('*_debug.log'), key=lambda x:x.stat().st_mtime_ns)[-1]; events=[RuntimeEvent.model_validate_json(line) for line in p.read_text(encoding='utf-8').splitlines() if line.strip()]; print(p.name, len(events), len({e.event_id for e in events}) == len(events))"
```

Expected: the file parses and event IDs are unique. If no debug file exists after migration, keep the already validated historical debug evidence and generate one only during the later user-approved GUI acceptance.

- [x] **Step 3: Run focused Plan B tests**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest -q `
  tests/unit/test_display_labels.py `
  tests/unit/infrastructure/test_application_paths.py `
  tests/unit/infrastructure/test_runtime_logging.py `
  tests/unit/migration/test_data_directory.py `
  tests/unit/engine/test_step_executor.py `
  tests/integration/test_project_store.py `
  tests/ui/test_region_capture.py `
  tests/ui/test_runtime_log.py `
  tests/ui/test_simple_shell.py `
  tests/ui/test_app_smoke.py `
  tests/ui/test_main_window.py `
  tests/ui/test_step_editors.py `
  tests/ui/test_step_templates.py
```

Expected: all selected tests pass.

- [x] **Step 4: Run the full automated suite and static checks**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest -q
python -m ruff check flow_runner tests scripts
python -m ruff format --check flow_runner tests scripts
python -m mypy flow_runner
python -m compileall -q flow_runner
python -m pip check
git diff --check
```

Expected: every command succeeds. Record the actual final test count and mypy source count in `REFACTOR_STATUS.md` and this plan.

- [x] **Step 5: Review the final repository diff and root layout**

Run:

```powershell
git status --short
git diff --stat
git diff --name-status
Get-ChildItem -Force | Select-Object Mode,Name
Get-ChildItem -Recurse -File -LiteralPath data | Select-Object FullName,Length
```

Expected: no unrelated user changes were reverted; removed historical files, archived documents, new modules/tests, and the `data/` layout are all explainable by Plan B.

- [x] **Step 6: Launch the application only after warning the user**

Tell the user that the next command opens the real GUI and writes a new session log under `data/logs/`. After confirmation, run:

```powershell
python -m flow_runner.app
```

- [x] **Step 7: Hand off the six manual checks**

Ask the user to verify:

1. Default startup loads the existing real project from `data/project.json`.
2. Groups, workflows, steps, routes, templates, and recordings still load.
3. Groups, workflows, and steps each show independent `01.`, `02.` numbering; no `1.2.1` format appears.
4. Stopping a repeatedly unsuccessful condition reports the actual completed detection count.
5. New logs, captured templates, and recordings appear only below `data/`.
6. No new project backup, log, screenshot, or recording appears at repository root.

- [x] **Step 8: Close Plan B without performing deferred tests**

After the six checks pass, mark Plan B complete and leave multi-monitor and Tesseract as `DEFERRED`. Do not install dependencies or alter display hardware/settings.

---

## New Session Start Prompt

Use this exact prompt in the new conversation:

```text
继续执行计划B：D:\3eyes\Python\codex\apps\flow_runner\PLAN_B.md

从 Task 0 开始，严格按 TDD 和清单顺序执行。当前分支有用户已验收但未提交的修改，禁止 reset、revert 或覆盖。迁移真实 project.json、备份、日志、模板和录制前先完成 dry-run、哈希与引用校验；涉及启动真实 GUI 或真实环境操作时先提示我确认。不要执行多显示器或 Tesseract 验收，不要自动 commit/push，不要使用子代理，除非我另行明确授权。
```

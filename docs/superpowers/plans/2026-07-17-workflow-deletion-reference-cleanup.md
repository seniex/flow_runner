# Workflow Deletion Reference Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow a confirmed workflow deletion to atomically remove inbound route references and repair the configured entry workflow while preserving parallel-block protection and undo.

**Architecture:** Keep reference discovery and immutable project transformation in `ProjectViewModel`; keep confirmation text and status feedback in `MainWindow`. The view model filters complete route rules that reference the deleted workflow, updates entry settings, validates once, and commits once so undo restores the entire change.

**Tech Stack:** Python 3.11+, PySide6, Pydantic v2, pytest, pytest-qt, Ruff, mypy

---

### Task 1: Reproduce route-reference deletion in the view model

**Files:**
- Modify: `tests/ui/test_main_window.py`
- Test: `tests/ui/test_main_window.py`

- [ ] **Step 1: Add routing predicate imports**

Replace the routing import with:

```python
from flow_runner.domain.routing import (
    ComparisonOperator,
    RoutePredicate,
    RouteRule,
    RouteTarget,
)
```

- [ ] **Step 2: Write a failing test for target and predicate references**

Add beside the existing `ProjectViewModel` tests:

```python
def test_remove_workflow_cleans_inbound_routes_and_undoes_atomically(qtbot):
    target = Workflow(name="目标")
    jump_route = RouteRule(
        outcome=StepOutcome.SUCCESS,
        target=RouteTarget.jump_workflow(target.id),
    )
    count_route = RouteRule(
        outcome=StepOutcome.FAILURE,
        predicate=RoutePredicate.workflow_count(
            target.id,
            ComparisonOperator.GE,
            1,
        ),
        target=RouteTarget.end(),
    )
    retained_route = RouteRule(
        outcome=StepOutcome.TIMEOUT,
        target=RouteTarget.end(),
    )
    source = Workflow(
        name="来源",
        steps=[AutomationStep(name="步骤", routes=[jump_route, count_route, retained_route])],
    )
    project = Project(
        name="p",
        groups=[FlowGroup(name="g", workflows=[source, target])],
        settings={"entry_workflow_id": str(source.id)},
    )
    model = ProjectViewModel(project)

    assert model.workflow_route_reference_count(target.id) == 2
    removed_routes = model.remove_workflow(target.id)

    assert removed_routes == 2
    assert model.project.groups[0].workflows == [
        source.model_copy(update={
            "steps": [source.steps[0].model_copy(update={"routes": [retained_route]})]
        })
    ]
    assert model.project.settings["entry_workflow_id"] == str(source.id)
    assert model.project.validate_references() == []
    model.undo()
    assert model.project == project
```

- [ ] **Step 3: Run the focused test and verify RED**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_main_window.py::test_remove_workflow_cleans_inbound_routes_and_undoes_atomically -v
```

Expected: FAIL because `workflow_route_reference_count` does not exist and current removal rejects the dangling references.

### Task 2: Implement atomic reference cleanup

**Files:**
- Modify: `flow_runner/ui/view_models/project_view_model.py:138`
- Test: `tests/ui/test_main_window.py`

- [ ] **Step 1: Import route types needed for reference matching**

Add:

```python
from flow_runner.domain.routing import RouteRule, RouteTargetKind
```

- [ ] **Step 2: Add the shared reference matcher and counter**

Add to `ProjectViewModel` before `remove_workflow`:

```python
    @staticmethod
    def _route_references_workflow(route: RouteRule, workflow_id: UUID) -> bool:
        target = route.target
        if (
            target.kind in {RouteTargetKind.JUMP_WORKFLOW, RouteTargetKind.CALL_WORKFLOW}
            and target.workflow_id == workflow_id
        ):
            return True
        predicate = route.predicate
        return (
            predicate is not None
            and predicate.source == "workflow_count"
            and predicate.key == str(workflow_id)
        )

    def workflow_route_reference_count(self, workflow_id: UUID) -> int:
        return sum(
            self._route_references_workflow(route, workflow_id)
            for group in self.project.groups
            for workflow in group.workflows
            if workflow.id != workflow_id
            for step in workflow.steps
            for route in step.routes
        )
```

- [ ] **Step 3: Replace `remove_workflow` with one immutable transaction**

Keep the existing parallel-block dependency check, then implement:

```python
    def remove_workflow(self, workflow_id: UUID) -> int:
        dependencies = [
            block.name
            for block in self.project.parallel_blocks
            if workflow_id in block.workflow_ids
        ]
        if dependencies:
            raise ConfigurationError(
                f"流程仍被并行监控块引用：{'、'.join(dependencies)}；请先编辑或删除这些并行块"
            )

        groups: list[FlowGroup] = []
        found = False
        removed_routes = 0
        for group in self.project.groups:
            workflows: list[Workflow] = []
            for workflow in group.workflows:
                if workflow.id == workflow_id:
                    found = True
                    continue
                steps: list[AutomationStep] = []
                for step in workflow.steps:
                    routes = [
                        route
                        for route in step.routes
                        if not self._route_references_workflow(route, workflow_id)
                    ]
                    removed_routes += len(step.routes) - len(routes)
                    steps.append(step.model_copy(update={"routes": routes}))
                workflows.append(workflow.model_copy(update={"steps": steps}))
            groups.append(group.model_copy(update={"workflows": workflows}))
        if not found:
            raise KeyError(workflow_id)

        settings = dict(self.project.settings)
        if settings.get("entry_workflow_id") == str(workflow_id):
            first_workflow = next(
                (workflow for group in groups for workflow in group.workflows),
                None,
            )
            if first_workflow is None:
                settings.pop("entry_workflow_id", None)
            else:
                settings["entry_workflow_id"] = str(first_workflow.id)

        self._commit(self.project.model_copy(update={"groups": groups, "settings": settings}))
        return removed_routes
```

- [ ] **Step 4: Run the focused test and verify GREEN**

Run the Task 1 command.

Expected: PASS.

- [ ] **Step 5: Run existing parallel-block protection test**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_main_window.py::test_delete_workflow_blocked_when_parallel_block_depends_on_it -v
```

Expected: PASS.

### Task 3: Cover entry-workflow repair and no-reference behavior

**Files:**
- Modify: `tests/ui/test_main_window.py`
- Test: `tests/ui/test_main_window.py`

- [ ] **Step 1: Add a failing entry-repair test**

```python
def test_remove_entry_workflow_selects_first_remaining_or_clears_setting(qtbot):
    first = Workflow(name="A")
    second = Workflow(name="B")
    project = Project(
        name="p",
        groups=[FlowGroup(name="g", workflows=[first, second])],
        settings={"entry_workflow_id": str(first.id)},
    )
    model = ProjectViewModel(project)

    assert model.remove_workflow(first.id) == 0
    assert model.project.settings["entry_workflow_id"] == str(second.id)

    assert model.remove_workflow(second.id) == 0
    assert "entry_workflow_id" not in model.project.settings
```

- [ ] **Step 2: Run the entry test**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_main_window.py::test_remove_entry_workflow_selects_first_remaining_or_clears_setting -v
```

Expected before Task 2 implementation: FAIL; expected after Task 2: PASS.

- [ ] **Step 3: Run all view-model deletion tests**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_main_window.py -k "remove_workflow or delete_workflow" -v
```

Expected: PASS.

### Task 4: Show cleanup impact in the UI and verify selection state

**Files:**
- Modify: `tests/ui/test_main_window.py`
- Modify: `flow_runner/ui/main_window.py:890`
- Test: `tests/ui/test_main_window.py`

- [ ] **Step 1: Write the failing UI regression test**

```python
def test_delete_referenced_workflow_confirms_cleanup_and_clears_selection(qtbot):
    target = Workflow(name="目标")
    source = Workflow(
        name="来源",
        steps=[
            AutomationStep(
                name="跳转",
                routes=[
                    RouteRule(
                        outcome=StepOutcome.SUCCESS,
                        target=RouteTarget.jump_workflow(target.id),
                    )
                ],
            )
        ],
    )
    confirmations = []
    window = MainWindow(
        Project(name="p", groups=[FlowGroup(name="g", workflows=[source, target])]),
        confirm_delete=lambda label: confirmations.append(label) or True,
    )
    qtbot.addWidget(window)
    window.flow_tree.select_workflow(target.id)

    window.delete_flow_action.trigger()

    assert len(confirmations) == 1
    assert "目标" in confirmations[0]
    assert "1 条引用路由" in confirmations[0]
    assert [workflow.id for workflow in window.view_model.project.groups[0].workflows] == [
        source.id
    ]
    assert window.view_model.project.groups[0].workflows[0].steps[0].routes == []
    assert window._workflow_id is None
    assert window.property_panel.step_id is None
    assert "已删除" in window.statusBar().currentMessage()
    assert "1 条引用路由" in window.statusBar().currentMessage()
```

- [ ] **Step 2: Run the UI test and verify RED**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_main_window.py::test_delete_referenced_workflow_confirms_cleanup_and_clears_selection -v
```

Expected: FAIL because the current confirmation does not report cleanup and deletion raises during reference validation.

- [ ] **Step 3: Update `_delete_selected_flow`**

Replace the successful workflow-deletion branch with:

```python
            reference_count = self.view_model.workflow_route_reference_count(workflow.id)
            cleanup_note = (
                f"，并同时删除 {reference_count} 条引用路由" if reference_count else ""
            )
            if self.confirm_delete(f"流程“{workflow.name}”{cleanup_note}"):
                removed_routes = self.view_model.remove_workflow(workflow.id)
                self._workflow_id = None
                self._refresh_context_actions()
                self.statusBar().showMessage(
                    f"已删除流程“{workflow.name}”并清理 {removed_routes} 条引用路由"
                )
            return
```

Retain the existing parallel-block dependency precheck above this branch.

- [ ] **Step 4: Run the UI test and verify GREEN**

Run the Task 4 Step 2 command.

Expected: PASS.

- [ ] **Step 5: Run the full main-window test module**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_main_window.py -q
```

Expected: PASS with no Qt slot exceptions or warnings.

### Task 5: Document behavior and run project verification

**Files:**
- Modify: `README.md`
- Verify: `flow_runner/ui/view_models/project_view_model.py`
- Verify: `flow_runner/ui/main_window.py`
- Verify: `tests/ui/test_main_window.py`

- [ ] **Step 1: Update workflow deletion documentation**

In the README editor-controls section, replace the sentence that only describes parallel-block protection with wording equivalent to:

```markdown
Existing parallel blocks can be edited, and a workflow cannot be deleted while a named parallel
block still depends on it. After confirmation, deleting any other workflow atomically removes route
rules that jump to, call, or count that workflow; deleting the configured entry workflow selects the
first remaining workflow, and one undo restores the complete change.
```

- [ ] **Step 2: Run focused tests**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest tests/ui/test_main_window.py -q
```

Expected: PASS.

- [ ] **Step 3: Run the full automated suite**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest
```

Expected: PASS.

- [ ] **Step 4: Run static quality checks**

```powershell
python -m ruff check flow_runner tests
python -m ruff format --check flow_runner tests
python -m mypy flow_runner
python -m compileall -q flow_runner
python -m pip check
git diff --check
```

Expected: every command exits successfully with no diagnostics requiring changes.

- [ ] **Step 5: Review the final working tree**

```powershell
git status --short
git diff -- flow_runner/ui/view_models/project_view_model.py flow_runner/ui/main_window.py tests/ui/test_main_window.py README.md docs/superpowers/specs/2026-07-16-workflow-deletion-reference-cleanup-design.md docs/superpowers/plans/2026-07-17-workflow-deletion-reference-cleanup.md
```

Expected: only the requested implementation, tests, and documentation appear; the pre-existing `data/project.json` modification remains untouched.

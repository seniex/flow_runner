# Route Target Step Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the same-workflow route target clear and editable, default new choices to the reordered workflow's next step, and preserve UUID-based targets across loading and step reordering.

**Architecture:** Keep route persistence unchanged: `RouteTarget.step_id` remains the stable UUID reference used by validation and runtime lookup. Limit production changes to the route editor's Qt presentation/default-selection logic and localization; verify step-reorder behavior through the existing immutable project/view-model and workflow executor interfaces.

**Tech Stack:** Python 3.12, PySide6, Pydantic, pytest, pytest-qt, Ruff.

---

### Task 1: Reproduce and specify route-editor behavior

**Files:**
- Modify: `tests/ui/test_step_editors.py`
- Test: `tests/ui/test_step_editors.py`

- [ ] **Step 1: Add failing tests for the label and editable control**

  Assert that `choice_label(RouteTargetKind.NEXT_STEP)` is `跳到本流程中的指定步骤`. After selecting `NEXT_STEP`, assert that `step_combo` is visible and enabled, then select another step and verify the created `RouteTarget.next_step(...)` uses that step's UUID.

- [ ] **Step 2: Add failing tests for default selection**

  Build a workflow with three steps, call `set_step_context()` for the first step, and assert the second step is selected by default. For the final step, assert `currentIndex() == -1` while all workflow steps remain available for manual selection.

- [ ] **Step 3: Add failing tests for existing targets and reordered workflows**

  Load an existing route whose target is not the sequential next step and assert its UUID is still displayed. Reorder the workflow steps while preserving every `AutomationStep.id`; assert a fresh route editor chooses the next UUID in the new order, while an existing route still displays its original target UUID.

- [ ] **Step 4: Run the focused tests and verify RED**

  Run:

  ```powershell
  $env:QT_QPA_PLATFORM='offscreen'
  .\.venv\Scripts\python.exe -m pytest -q tests\ui\test_step_editors.py -k "route_editor and (next_step or same_workflow or reordered)"
  ```

  Expected: failures show the old Chinese label, hidden target-step combo, first-step default, or missing reorder behavior.

### Task 2: Implement the focused route-editor fix

**Files:**
- Modify: `flow_runner/ui/localization.py:120`
- Modify: `flow_runner/ui/editors/route_editor.py:156-172`
- Modify: `flow_runner/ui/editors/route_editor.py:367-373`
- Test: `tests/ui/test_step_editors.py`

- [ ] **Step 1: Update the localized target label**

  Change only the `next_step` choice label to `跳到本流程中的指定步骤`.

- [ ] **Step 2: Replace the Qt enum identity check**

  In `_update_controls()`, compare `currentData()` by value (`==`) rather than object identity (`is`) so Qt's returned plain string `"next_step"` correctly reveals `step_combo`.

- [ ] **Step 3: Select the ordered next step without overwriting loaded routes**

  In `set_step_context()`:

  - find the current step's index in its containing workflow;
  - populate all steps so backward, forward, and self targets remain manually selectable;
  - when entering a new step context or editing an empty route list, select `current_index + 1`;
  - when the current step is last, set index `-1`;
  - when refreshing the same step with an existing `NEXT_STEP` route, preserve the selected target UUID;
  - allow `_load_current()` to remain the final authority when loading an existing route.

- [ ] **Step 4: Run the focused tests and verify GREEN**

  Run the Task 1 command. Expected: all selected tests pass.

### Task 3: Verify UUID stability through user step reordering

**Files:**
- Modify: `tests/ui/test_main_window.py`
- Test: `tests/ui/test_main_window.py`
- Test: `tests/unit/engine/test_workflow_executor.py`

- [ ] **Step 1: Add a regression test for the step toolbar**

  Create a source step with `RouteTarget.next_step(target.id)`, move either source or target with the existing toolbar action, and assert:

  - the ordered `workflow.steps` list changed;
  - every moved step retained its original UUID;
  - the route still contains `target.id`, not a positional index or a newly generated UUID;
  - `project.validate_references()` remains empty.

- [ ] **Step 2: Verify runtime lookup remains UUID-based**

  Run the relevant workflow-executor tests and confirm `_step_by_id()` follows the explicit route target after reordering. Add a focused executor regression only if current coverage does not prove the reordered case.

- [ ] **Step 3: Run reorder and engine tests**

  ```powershell
  $env:QT_QPA_PLATFORM='offscreen'
  .\.venv\Scripts\python.exe -m pytest -q tests\ui\test_main_window.py -k "move_step"
  .\.venv\Scripts\python.exe -m pytest -q tests\unit\engine\test_workflow_executor.py
  ```

  Expected: all selected tests pass.

### Task 4: Regression verification and handoff

**Files:**
- Verify only: `project.json`
- Verify only: `project.1783970691838055900.bak.json`
- Verify only: `project.1783970779196284800.bak.json`

- [ ] **Step 1: Run the complete UI editor test file**

  ```powershell
  $env:QT_QPA_PLATFORM='offscreen'
  .\.venv\Scripts\python.exe -m pytest -q tests\ui\test_step_editors.py tests\ui\test_main_window.py
  ```

- [ ] **Step 2: Run the complete test suite**

  ```powershell
  $env:QT_QPA_PLATFORM='offscreen'
  .\.venv\Scripts\python.exe -m pytest -q
  ```

- [ ] **Step 3: Run static checks**

  ```powershell
  .\.venv\Scripts\python.exe -m ruff check flow_runner tests
  .\.venv\Scripts\python.exe -m ruff format --check flow_runner tests
  git diff --check
  ```

- [ ] **Step 4: Review the final diff**

  Confirm production changes are limited to localization and route-editor presentation/default logic, tests cover UUID reordering, and the pre-existing `project.json` plus both backup files were not modified by this task. Do not commit unless the user explicitly requests it.

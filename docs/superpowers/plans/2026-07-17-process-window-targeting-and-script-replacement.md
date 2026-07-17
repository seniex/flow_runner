# Process Window Targeting and Script Replacement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add stable process-name targeting to built-in window conditions/actions, retain legacy title configurations, and replace every known standalone window-control launch in the active project with equivalent synchronous built-in actions.

**Architecture:** A shared immutable `WindowTarget` model validates the mutually exclusive process/title selector and exposes ordered process names and resource keys. The Win32 adapter enumerates visible top-level windows once per operation, resolves executable basenames through `QueryFullProcessImageNameW`, and applies deterministic selection rules; capability providers pass selector diagnostics through condition/action results. A pure migration helper maps known script basenames to action sequences and is used both by legacy conversion and a one-time active-project migration.

**Tech Stack:** Python 3.11+, Pydantic 2, PySide6, pywin32/ctypes on Windows, pytest, pytest-qt, Ruff, mypy

---

## File Map

- Create `flow_runner/domain/window_targets.py`: validated process/title selector, normalization, ordered fallback names, and resource-key helpers.
- Modify `flow_runner/capabilities/actions/window.py`: inherit shared selector fields, dispatch selectors, return backend diagnostics, and preserve title compatibility.
- Modify `flow_runner/capabilities/conditions/window.py`: use the shared selector and expose process/window diagnostics and foreground matching.
- Modify `flow_runner/infrastructure/windowing/win32.py`: extend protocols, enumerate Win32 candidates, resolve process basenames, select matches, and implement activate/minimize/restore/move-resize semantics.
- Modify `flow_runner/ui/localization.py`, `flow_runner/ui/editor_metadata.py`, `flow_runner/ui/editors/model_form.py` only where needed for process/fallback labels and selector display; keep title available in advanced JSON.
- Modify `flow_runner/ui/step_templates.py` and `flow_runner/ui/dialogs/template_step_dialog.py`: change the guided activation template from a title parameter to a process-name parameter.
- Create `flow_runner/migration/window_controls.py`: script-basename mapping and immutable `Project` migration helper.
- Modify `flow_runner/migration/legacy.py`: invoke the mapping during future legacy conversion before constructing a `system.launch` action.
- Create `scripts/migrate_window_control_actions.py`: dry-run/apply wrapper that loads and atomically saves the active project through `ProjectStore`.
- Modify `data/project.json`: replace only the confirmed five script launch families; preserve IDs, routes, explicit waits, recordings, and unrelated launch actions.
- Modify `README.md`: describe process-name window actions/conditions and legacy title compatibility.
- Add focused tests under `tests/unit/domain`, `tests/unit/infrastructure`, `tests/unit/migration`, `tests/integration`, and `tests/ui` named in the tasks below.

Do not modify `Screenshot 2026-07-17 065554.png`, `UI.png`, recordings, `pet_explore.pyw` launches, or `auto_war3.py` launches. Do not commit unless explicitly requested.

## Task 1: Shared Selector Model and Capability Contracts

**Files:**
- Create `flow_runner/domain/window_targets.py`
- Modify `flow_runner/capabilities/actions/window.py`
- Modify `flow_runner/capabilities/conditions/window.py`
- Create `tests/unit/domain/test_window_targets.py`
- Modify `tests/integration/test_parallel_monitors.py`
- Modify `tests/integration/test_system_conditions.py`

- [ ] **Step 1: Write failing selector validation tests**

Add tests for the exact public model:

```python
import pytest
from pydantic import ValidationError

from flow_runner.domain.window_targets import WindowTarget


def test_process_target_normalizes_ordered_names_and_deduplicates_fallbacks():
    target = WindowTarget(
        process_name=" Chrome.EXE ",
        fallback_process_names=["PotPlayerMini64.exe", "chrome.exe", "potplayer.exe"],
    )
    assert target.process_names == (
        "Chrome.EXE",
        "PotPlayerMini64.exe",
        "potplayer.exe",
    )
    assert target.matching_process_names == ("chrome.exe", "potplayermini64.exe", "potplayer.exe")


@pytest.mark.parametrize(
    "payload",
    [{}, {"process_name": "", "title": "Game"}, {"process_name": "chrome.exe", "title": "Game"}],
)
def test_target_requires_exactly_one_non_empty_selector(payload):
    with pytest.raises(ValidationError):
        WindowTarget.model_validate(payload)


def test_title_target_keeps_legacy_selector_and_resource_key():
    target = WindowTarget(title="懒人修仙传2")
    assert target.process_names == ()
    assert target.resource_key == "window:懒人修仙传2"
```

- [ ] **Step 2: Run the selector tests and verify the expected failure**

Run:

```powershell
python -m pytest tests/unit/domain/test_window_targets.py -q
```

Expected: collection fails because `WindowTarget` does not exist.

- [ ] **Step 3: Implement the immutable selector and config inheritance**

Implement `WindowTarget` with frozen Pydantic fields `process_name: str | None`,
`fallback_process_names: list[str]`, and `title: str | None`; strip whitespace, reject an empty
effective selector, reject process-plus-title combinations, preserve the first spelling for display,
deduplicate fallback names case-insensitively, and expose:

```python
@property
def process_names(self) -> tuple[str, ...]:
    if self.process_name is None:
        return ()
    return (self.process_name, *self.fallback_process_names)

@property
def matching_process_names(self) -> tuple[str, ...]:
    return tuple(name.casefold() for name in self.process_names)

@property
def resource_key(self) -> str:
    if self.process_names:
        return "window:process:" + "|".join(self.matching_process_names)
    return f"window:{self.title}"
```

Make `WindowActionConfig(WindowTarget)` add `operation` and optional geometry, and make
`WindowConditionConfig(WindowTarget)` add `require_foreground`. Provider protocols accept a
`WindowTarget`, while title callers remain valid through `WindowTarget(title=...)`. `WindowAction`
must return `ActionResult(outcome=SUCCESS, provider_data=backend_data)` and use the selector's
resource key; `WindowCondition` must evaluate `exists` plus `require_foreground` and preserve all
backend data.

- [ ] **Step 4: Run capability tests and update fakes to the selector contract**

Run:

```powershell
python -m pytest tests/unit/domain/test_window_targets.py tests/integration/test_parallel_monitors.py tests/integration/test_system_conditions.py -q
```

Expected: the new selector tests and updated fake-controller/query assertions pass; backend-specific
tests remain pending until Task 2.

## Task 2: Win32 Enumeration, Matching, and Deterministic Operations

**Files:**
- Modify `flow_runner/infrastructure/windowing/win32.py`
- Create `tests/unit/infrastructure/test_win32_window_matching.py`
- Modify `tests/integration/test_parallel_monitors.py`
- Modify `tests/integration/test_system_conditions.py`

- [ ] **Step 1: Write failing backend tests with injected Win32 modules**

Create fake `win32gui`, `win32con`, `win32process`, and process-image resolver objects. The process
fallback test must return Chrome candidates only after the primary name is absent and assert that
PotPlayer candidates are then selected; the selection test must cover foreground, non-minimized,
and enumeration-order candidates in three separate cases; the multi-window test must assert two
`SW_MINIMIZE` and two `SW_RESTORE` calls; and the geometry test must assert one `SetWindowPos` call.
Each test must assert concrete `ShowWindow`, `SetForegroundWindow`, and `SetWindowPos` calls,
including that `restore` never calls `SetForegroundWindow` and `move_resize` uses `SWP_NOZORDER`.

- [ ] **Step 2: Run the backend tests and verify the expected failure**

Run:

```powershell
python -m pytest tests/unit/infrastructure/test_win32_window_matching.py -q
```

Expected: failures because the protocols and process-aware backend do not exist.

- [ ] **Step 3: Implement candidate enumeration and process resolution**

Add an internal immutable candidate record containing handle, title, PID, executable basename,
foreground, and minimized state. Enumerate only visible top-level windows with non-empty titles.
Resolve the basename using `OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)`,
`QueryFullProcessImageNameW`, and `CloseHandle`; catch lookup failures per window and continue.
Keep all platform imports lazy/injectable so Linux test runs do not import pywin32.

- [ ] **Step 4: Implement selector matching and operation semantics**

For process targets, iterate primary then fallback names and return only the first name's matching
set. For title targets, retain the existing first-match substring behavior. Select one window for
activate/move-resize as foreground first, then non-minimized, then enumeration order. `activate`
restores and foregrounds it; if the Windows foreground-lock restriction prevents the first call,
send a zero-duration Alt key tap through the injected Win32 keyboard adapter and retry once. `minimize`
minimizes every selected window; `restore` restores every selected window without foregrounding;
`move_resize` changes only the selected window. Raise `LookupError` with all attempted process names
or the title when no candidate exists. Return a JSON-safe diagnostics mapping with selector,
matched handles/titles, selected handle, process names, foreground, and minimized state.

- [ ] **Step 5: Run backend and capability tests**

Run:

```powershell
python -m pytest tests/unit/infrastructure/test_win32_window_matching.py tests/integration/test_parallel_monitors.py tests/integration/test_system_conditions.py -q
```

Expected: all selected tests pass, including legacy title calls and process fallback behavior.

## Task 3: Guided UI, Localization, and Templates

**Files:**
- Modify `flow_runner/ui/localization.py`
- Modify `flow_runner/ui/editor_metadata.py`
- Modify `flow_runner/ui/step_templates.py`
- Modify `flow_runner/ui/dialogs/template_step_dialog.py`
- Modify `tests/ui/test_localized_ui.py`
- Modify `tests/ui/test_compact_layout.py`
- Modify `tests/ui/test_model_form_modes.py`
- Modify `tests/ui/test_step_templates.py`

- [ ] **Step 1: Write failing UI and template tests**

Assert that `field_label("process_name")` is `"进程名"`, `field_label("fallback_process_names")`
is `"备用进程名"`, common fields for both window capabilities expose process selectors and
`require_foreground`, and `title` is advanced. Add a model-form test that a legacy
`{"title": "Game"}` value round-trips while the process field remains empty. Change the activation
template fixture to pass `window_process_name="chrome.exe"` and assert the generated action contains
`process_name` rather than `title`.

- [ ] **Step 2: Run focused UI tests and verify the expected failure**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/ui/test_localized_ui.py tests/ui/test_compact_layout.py tests/ui/test_model_form_modes.py tests/ui/test_step_templates.py -q
```

Expected: failures for missing labels, metadata, and process-based template output.

- [ ] **Step 3: Implement metadata and template changes**

Add labels and common-field declarations without removing the `title` field from the Pydantic model.
Keep advanced JSON serialization unchanged for legacy title data. In the template dialog rename the
editor, row label, parameter map, and builder parameter to `window_process_name`; retain the template
ID so existing callers do not break.

- [ ] **Step 4: Run focused UI tests and inspect summaries**

Run the same offscreen pytest command. Then run:

```powershell
python -m ruff check flow_runner/ui tests/ui
```

Expected: all focused tests pass and Ruff reports no errors. Confirm window action summaries display
the process name plus fallbacks for new configs and the title for legacy configs.

## Task 4: Script Replacement Mapping and Legacy Conversion

**Files:**
- Create `flow_runner/migration/window_controls.py`
- Modify `flow_runner/migration/legacy.py`
- Create `tests/unit/migration/test_window_controls.py`
- Modify `tests/unit/migration/test_legacy.py`

- [ ] **Step 1: Write failing mapping and preservation tests**

Add tests for exact action sequences. `test_min_lanren_maps_to_minimize_lanren2` must assert one
`system.window_action` minimize action with `process_name == "lanren2.exe"`;
`test_restore_lanren_maps_to_activate_lanren2` must assert one activate action with the same
process; `test_min_maps_to_war3_minimize_wait_03_and_chrome_activation` must assert the exact
three-action order and fallback list; `test_restore_maps_to_war3_activation_with_warcraft_fallback`
must assert the War3 fallback list; `test_restore_platform_maps_to_platform_activation` must
assert the Platform process; `test_unknown_scripts_and_recordings_are_unchanged` must compare the
original launch/playback `ActionSpec` objects; and
`test_project_migration_preserves_step_ids_routes_existing_waits_and_non_window_launches` must
compare all IDs/routes and assert an existing `system.wait` remains after the replacement.
Assert `min.py` produces exactly three actions with `system.wait.seconds == 0.3`, while an existing
explicit wait remains after the replacement sequence rather than being removed or duplicated.

- [ ] **Step 2: Run migration tests and verify the expected failure**

Run:

```powershell
python -m pytest tests/unit/migration/test_window_controls.py tests/unit/migration/test_legacy.py -q
```

Expected: failures because the mapping module is absent and legacy conversion still emits launch
actions for known helper scripts.

- [ ] **Step 3: Implement pure action mapping and immutable project transformation**

Match `Path(arguments[0]).name.casefold()` for the five confirmed helper names. Return built-in
actions with these exact configs:

```python
{"operation": "minimize", "process_name": "lanren2.exe"}
{"operation": "activate", "process_name": "lanren2.exe"}
{"operation": "minimize", "process_name": "war3.exe", "fallback_process_names": ["warcraft iii.exe"]}
{"capability": "system.wait", "config": {"seconds": 0.3}}
{"operation": "activate", "process_name": "chrome.exe", "fallback_process_names": ["PotPlayerMini64.exe", "potplayer.exe"]}
{"operation": "activate", "process_name": "war3.exe", "fallback_process_names": ["warcraft iii.exe"]}
{"operation": "activate", "process_name": "platform.exe"}
```

Use `model_copy(update={"actions": actions})` for steps and equivalent explicit dictionaries for
workflows/groups/project so IDs, routes, settings, and all
unmatched actions remain byte-for-byte represented at the model level. Call this helper from
`legacy._convert_launch_actions` before the normal launch conversion.

- [ ] **Step 4: Run migration tests and inspect action counts**

Run:

```powershell
python -m pytest tests/unit/migration/test_window_controls.py tests/unit/migration/test_legacy.py -q
```

Expected: all migration tests pass; the full legacy fixture still has valid references and retains
recording/program-launch actions.

## Task 5: Active Project Migration and Safe CLI

**Files:**
- Create `scripts/migrate_window_control_actions.py`
- Modify `tests/unit/migration/test_window_controls.py`
- Modify `data/project.json` only through the tested script

- [ ] **Step 1: Write a dry-run/apply CLI test**

Build a temporary project with one known script launch and one unrelated launch, invoke the script
with `--project <path>` (dry run) and `--apply`, then assert dry run leaves bytes unchanged, apply
creates a ProjectStore backup, and the migrated JSON validates.

- [ ] **Step 2: Run the CLI test and verify the expected failure**

Run:

```powershell
python -m pytest tests/unit/migration/test_window_controls.py -q
```

Expected: failure because the CLI is absent.

- [ ] **Step 3: Implement the CLI and apply it to the active project**

The CLI must default to dry-run, print each replacement count and script family, require explicit
`--apply` to write, load through `ProjectStore`, call the pure project migration, and save through
`ProjectStore.save` so validation, temporary-file flush, atomic replacement, and backup rotation are
used. Run:

```powershell
python scripts/migrate_window_control_actions.py --project data/project.json
python scripts/migrate_window_control_actions.py --project data/project.json --apply
```

Before and after applying, record counts for the five removed script basenames and verify zero
occurrences of those basenames remain in `system.launch` arguments. Verify `pet_explore.pyw`,
`auto_war3.py`, all recording paths, IDs, routes, and user-edited click timing/coordinates remain.

- [ ] **Step 4: Run project validation and migration regression tests**

Run:

```powershell
python -m pytest tests/unit/migration/test_window_controls.py tests/integration/test_project_store.py -q
python -c "from pathlib import Path; from flow_runner.infrastructure.persistence.project_store import ProjectStore; print(ProjectStore(Path('data/project.json')).load().validate_references())"
```

Expected: zero test failures and the final command prints `[]`.

## Task 6: Documentation, Full Verification, and Real Windows Acceptance

**Files:**
- Modify `README.md`
- Modify `REAL_ENVIRONMENT_CHECKLIST.md` only to add this feature's acceptance rows if the existing
  checklist format requires a record

- [ ] **Step 1: Document the selector and compatibility behavior**

Update the window-action editor paragraph to say new actions use executable process names with
ordered fallbacks, while existing title-only JSON remains supported through advanced JSON. Clarify
that process actions select all matching windows for minimize/restore and a deterministic single
window for activate/move-resize.

- [ ] **Step 2: Run focused automated verification**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; python -m pytest tests/unit/domain/test_window_targets.py tests/unit/infrastructure/test_win32_window_matching.py tests/unit/migration/test_window_controls.py tests/integration/test_parallel_monitors.py tests/integration/test_system_conditions.py tests/ui/test_localized_ui.py tests/ui/test_compact_layout.py tests/ui/test_model_form_modes.py tests/ui/test_step_templates.py -q
```

Expected: all selected tests pass.

- [ ] **Step 3: Run repository quality checks**

Run:

```powershell
python -m ruff check flow_runner tests scripts
python -m mypy flow_runner
python -m compileall flow_runner tests scripts
git diff --check
```

Expected: all commands exit successfully with no errors. Do not claim completion from a partial
check.

- [ ] **Step 4: Run the complete suite and inspect the final diff**

Run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; python -m pytest -q
git status --short
git diff --stat
git diff -- data/project.json flow_runner tests scripts README.md docs/superpowers/plans/2026-07-17-process-window-targeting-and-script-replacement.md
```

Expected: the complete suite passes; only planned source/tests/docs/CLI changes plus the user's
pre-existing `data/project.json` diff and screenshots are present.

- [ ] **Step 5: Perform real Windows acceptance**

With LanRen2, War3, Chrome/PotPlayer, and Platform running, verify process-name matching is
case-insensitive; fallback selection uses the first available executable; activate restores and
foregrounds the selected window; minimize/restore cover every top-level window owned by the process;
move-resize does not change foreground; and missing processes produce a clear attempted-name error.
Run the affected workflows and confirm `min.py` replacement minimizes War3, waits 0.3 seconds,
then activates Chrome/PotPlayer before the next click. Record evidence in the checklist and report
any environment-only limitation instead of inferring success.

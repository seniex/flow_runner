# Flow Runner Qt

Flow Runner Qt is a composable desktop-automation workflow editor and runtime for game
automation. The new implementation uses typed conditions, actions, policies, and routes instead
of fixed OCR/image step combinations.

## Current release

Current version: `0.2.0`.

- Groups, workflows, and steps use independent two-digit display numbers without changing raw
  names, UUIDs, JSON data, or route references.
- Active configuration and runtime data live under `data/`; legacy conversion inputs and historical
  project documents are archived separately.
- Normal/debug logging, the wait-action countdown, and preserved condition-attempt counts on
  cancellation passed the six-item real-GUI acceptance.
- Latest verification: 337 tests passed; Ruff, formatting, mypy, compileall, and pip check
  succeeded.
- Multi-monitor and Tesseract real-environment acceptance remain `DEFERRED`; see
  [`REAL_ENVIRONMENT_CHECKLIST.md`](REAL_ENVIRONMENT_CHECKLIST.md).

## Requirements

- Python 3.11 or newer
- Windows for real desktop input, Win32 capture, and global-hotkey integration
- PaddleOCR-json or Tesseract when the corresponding OCR adapter is enabled

## Installation

### Recommended: project virtual environment

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
```

### Alternative: global Python

This modifies the shared Python environment and can affect other installed applications.

```powershell
python -m pip install -e ".[test]"
```

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Qt tests run without a visible desktop:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest tests/ui
```

## Running

Recommended project virtual environment:

```powershell
.\.venv\Scripts\python.exe -m flow_runner.app
```

Global Python alternative:

```powershell
python -m flow_runner.app
```

After installation, the console entry point is also available:

```powershell
flow-runner
```

All three commands load `data/project.json` by default. Backups, generated templates, recordings,
and logs are written under `data/` in their corresponding subdirectories. An explicitly supplied
`project_path` keeps those auxiliary directories beside that project file. Visual styling is loaded
application-wide from `flow_runner/resources/styles/base.qss`. The default theme is a dark,
QSS-driven workspace; Python UI modules do not contain local color styles.

OCR engine selection is stored in the project `settings` object. PaddleOCR-json v1.4.x uses its
stdin/stdout JSON protocol and is started lazily on the first OCR request:

```json
{
  "settings": {
    "ocr_engine": "paddle",
    "paddle_exe_path": "PaddleOCR-json_v1.4.1/PaddleOCR-json.exe",
    "window_capture_mode": "background",
    "window_capture_fallback": true,
    "window_capture_timeout_seconds": 3.0
  }
}
```

With the default `data/project.json`, relative third-party executable paths are resolved from the
application root. With an explicitly supplied `project_path`, they are resolved from that project
file's directory. The local `PaddleOCR-json_v*/` folder is intentionally ignored by Git because it
contains large third-party binaries. Use `"ocr_engine": "tesseract"` to use the Tesseract adapter
instead.

Tesseract additionally requires `pytesseract`, a locally installed Tesseract executable, and the
language data named by each OCR condition. These are real-environment dependencies and are not
started or downloaded by Flow Runner.

## Workflow model

Each `AutomationStep` combines four independent parts:

- an optional leaf or AND/OR/NOT condition tree;
- actions that run only after the condition matches;
- condition/action attempt and timeout policies;
- ordered result routes for success, one-shot no-match, timeout, failure, and cancellation.

Routes use stable UUID references and can continue within the current workflow, jump or call any
workflow across groups, return to a caller, or end the task. Optional route predicates can compare
task/workflow variables and workflow/step execution counts. ONCE evaluates once and produces
`not_matched`; UNTIL polls until it matches or produces `timeout`.

Condition results remain available to actions and routes for the current step. A leaf or uniquely
matched OR branch exposes `$result.primary`; AND, NOT, and ambiguous OR results require an explicit
named child such as `$result.children["ocr_a"].position`.

Visual targets use `desktop` for the complete virtual desktop or `window:窗口标题` for a matching
visible Win32 window. The project setting `window_capture_mode` chooses the default window backend:
`foreground` reads the currently visible pixels with BitBlt, while `background` uses Windows
Graphics Capture and continues receiving the target window while another window covers it. A target
can override the project default with `window:foreground:窗口标题` or
`window:background:窗口标题`. If configured, background failures fall back to foreground capture and
the condition result reports the requested mode, actual mode, and failure reason instead of hiding
the fallback. Both target forms share one scene generation and resource lock.

Captures retain their virtual-screen/window origin, so OCR, template, and pixel positions exposed to
mouse actions are absolute screen coordinates even when a monitor is left of the primary display.
The application enables Per-Monitor V2 DPI awareness before constructing Qt.

## Editor and runtime controls

The default workspace keeps groups/workflows on the left, expandable step cards and detailed
properties in the main area, and a persistent runtime log at the bottom. The runtime toolbar has
independent startup group/workflow selectors; the selected entry is stored as
`settings.entry_workflow_id`, so editing another workflow does not silently change what Start runs.
Groups, workflows, and steps display independent two-digit numbers that restart inside their direct
container. These labels are presentation-only: raw names, UUIDs, JSON data, and route references are
unchanged.
New steps start from only three guided categories: `检测`, `执行`, and `控制`. Conditions can later
switch capabilities or be combined in the guided AND/OR/NOT tree without changing the surrounding
policy and routes. Advanced JSON remains available for direct schema-level editing.

The three editor columns share one draggable splitter. Their widths are stored in
`settings.ui_layout.column_widths` only when the project is saved and restored on the next launch.
Collapsed step cards show only the step name; the selected card replaces the name with its compact
detection, action, policy, and route summary. Window actions keep operation, title, and geometry on
one row, showing geometry only for move/resize.

Step properties open on a compact `常用配置` tab. Capability-specific advanced fields can be
revealed when needed, while the separate `高级 JSON` tab round-trips conditions, actions, policies,
and routes through the same validation path. Policy and route summaries use readable project names;
an unconditional route that would hide a later conditional route is rejected before save.
Common action, detection, policy, and route fields use a wrapping horizontal layout: controls stay
on one row while space permits and wrap only in narrower windows. Complex condition trees, action
sequences, and advanced policy hooks retain dedicated editing areas.

Visual condition forms can capture a region directly from a frozen desktop/window frame. Region
fields expose `框选区域`; image-template forms additionally expose `框选并截图`, which fills the
selected region and writes a PNG below `data/templates/` for recognition.

The project toolbar supports group/workflow/step editing, undo, validated save, settings, and
explicit parallel blocks. Parallel execution is never inferred from routes: create a parallel block
and select the workflows that should monitor concurrently. Children share task variables and runtime
resources while retaining separate workflow-local variables and call stacks.

Six common step templates cover OCR-and-click, OCR timeout continuation, delayed input, window
activation plus input, count-based workflow jumps, and success/timeout branches. Steps, workflows,
and groups can be copied with new UUIDs; references inside the copied scope are remapped while
external references remain unchanged. Existing parallel blocks can be edited, and a workflow cannot
be deleted while a named parallel block still depends on it.

The guided editor displays built-in capabilities, parameter names, choices, route outcomes, and
runtime states in Chinese while retaining stable English schema keys in advanced JSON. A single step
can freely mix and reorder mouse, keyboard, wait, variable, process, playback, and window actions;
the sequence list shows a readable summary rather than internal capability identifiers.

Saving from the toolbar or with `Ctrl+S` first commits the currently edited condition, selected
action, policy hooks, route, and step, then validates and atomically writes the complete project. It
is no longer necessary to click each nested “更新动作” and “应用” button before saving. Pending
values are also committed in memory before switching steps, and closing with pending form values
uses the same unsaved-change confirmation. Changes saved during a run take effect on the next run.

Configuration combo boxes and numeric inputs respond to the mouse wheel only while they have
keyboard focus. Scrolling the property panel over an unfocused field therefore scrolls the panel
without changing the parameter; click or Tab into the field before using the wheel to edit it.

Undo first discards unapplied values in the current property form, then operates on project history.
A successful save starts a new undo boundary, so undo cannot cross back into changes made before
that save. Closing while a task is running uses one explicit decision dialog: save (when needed)
happens before stopping, a failed save does not stop the task, and a stop timeout keeps the window
open.

The runtime toolbar provides start, pause/resume, stop, input recording, selected-step execution,
condition preview, and structured diagnostics. Visual condition previews attach the recent frame as
an in-memory PNG without creating temporary screenshot files. Diagnostics include step results,
selected routes, frame/scene identifiers, retry data, errors, and resource wait events. A
`system.wait` action displays a one-second, in-place countdown in the runtime log; pause freezes it
and cancellation replaces it with a final cancelled entry. Default global hotkeys are
F6 start, F7 stop, F8 pause/resume, and F9 recording; project settings can change or disable them.

Recordings are stored by default at `data/recordings/latest.json`. The playback action can reuse a
recording with configurable speed and maximum gap.

Mouse actions support fixed or result-bound coordinates, an additional coordinate offset, click,
move, scroll, button-down, button-up, and drag operations. Keyboard actions support press, hotkey,
text entry, key-down, and key-up. Text entry has three per-action modes: `keys` sends physical key
events and remains the default for game compatibility, `unicode` sends Windows Unicode input for
layout-independent Chinese or other text, and `clipboard` pastes text before restoring the previous
clipboard formats. Ordered step actions form input sequences without a separate sequence step type.
Long moves, drags, repeated keys, and interval text are divided into cancellable segments. Tracked
held inputs are released whenever a run terminates or the application shuts down; recording
playback also releases held keys on cancellation.

Program launch actions accept an optional `working_directory` and `hide_window` flag. Normal
launches pass the working directory to the child process and use `CREATE_NO_WINDOW` when hidden;
administrator launches pass both settings to `ShellExecuteW`. If the working directory is omitted,
normal launches inherit the current directory and administrator launches use the executable
directory. Converted `.py` and `.pyw` helpers are hidden by default so they cannot cover the game or
steal visible screen space.

## Persistence and safety

Project JSON, UUID references, registered condition/action configs, policy hooks, and runtime binding
syntax are validated on load and again before save. Saves write and validate a temporary sibling file,
flush it, rotate the five newest backups under `data/backups/`, and atomically replace the main file.
Desktop/window interactions
are coordinated so read-only detection can share frames while conflicting input is serialized.
Screen-derived coordinates are revalidated under the exclusive interaction lease if another action
has changed the scene. Fixed absolute coordinates remain serialized but do not re-run the original
condition between actions. Every application launch creates one new log under `data/logs/`, named
`flow_runner_<YYYYMMDD_HHMMSS>_normal.log` by default. Normal logs contain concise
Chinese names, outcomes, routes, errors, and wait boundaries. Enabling `debug_logging` takes effect
on the next launch and creates a `_debug.log` file containing one complete RuntimeEvent JSON object
per line. Existing historical logs are never overwritten.

## Real Windows acceptance

Automated tests use fake capture, OCR, input, window, and process adapters. Before release, execute
every item in `REAL_ENVIRONMENT_CHECKLIST.md` on the target Windows/game environment. PaddleOCR-json
v1.4.x is managed by the application when configured as above. Tesseract requires `pytesseract`,
the Tesseract executable, and the requested language data.

## Architecture

- `flow_runner/domain`: validated project, workflow, condition, action, policy, and routing models
- `flow_runner/engine`: Qt-independent execution, context, perception, and resource coordination
- `flow_runner/capabilities`: registered condition and action providers
- `flow_runner/infrastructure`: screenshot, OCR, input, persistence, and logging adapters
- `flow_runner/ui`: PySide6 views, ViewModels, dialogs, and application-wide QSS management

The obsolete `flow_runner_p1.py`, `flow_runner_p2.py`, and `flow_runner_p3.py` implementations were
removed after confirming that the current package, tests, and runtime configuration do not import
them. The active project was originally generated from the archived legacy configuration by
`python -m flow_runner.migration.cli`; converted recordings are stored in
`data/recordings/legacy/`. See
[`docs/archive/LEGACY_CONVERSION_REPORT.md`](docs/archive/LEGACY_CONVERSION_REPORT.md) for the exact
mappings and validation evidence.

The dark workspace follows the
[`flowUI.png`](docs/assets/ui-references/flowUI.png) and
[`BGUI.png`](docs/assets/ui-references/BGUI.png) references through the shared QSS and compact
layout system; those reference files are not runtime dependencies.

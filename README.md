# Flow Runner Qt

Flow Runner Qt is a composable desktop-automation workflow editor and runtime for game
automation. The new implementation uses typed conditions, actions, policies, and routes instead
of fixed OCR/image step combinations.

## Current release

Current version: `0.4.1`.

- Groups, workflows, and steps use independent two-digit display numbers without changing raw
  names, UUIDs, JSON data, or route references.
- Active configuration and runtime data live under `data/`; legacy conversion inputs and historical
  project documents are archived separately.
- Normal/debug logging, the wait-action countdown, and preserved condition-attempt counts on
  cancellation passed the six-item real-GUI acceptance.
- The automated quality gate covers pytest, Ruff, formatting, mypy, compileall, and pip dependency
  consistency; the current run result is reported in each release handoff rather than hard-coded
  here.
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

Windows double-click launcher:

- Double-click `start_flow_runner.pyw` in the project root.
- This uses the global `pythonw.exe` associated with `.pyw` files, so install the project with the
  global Python method first.
- It loads `data/project.json` without opening a console window.
- Startup failures show an error dialog and write details to `data/launcher_error.log`.

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

The default workspace keeps groups/workflows on the left, expanded step cards in the middle,
detailed properties on the right, and a persistent runtime log at the bottom. Controls live with
the content they affect: the left column contains runtime, group/workflow, and parallel-block
controls; the middle column contains step editing, selected-step execution, and condition preview;
the right column contains save, undo, settings, and diagnostics. Each column wraps its controls
onto additional rows as the user narrows that column. The startup group/workflow selectors are
independent; the selected entry is stored as
`settings.entry_workflow_id`, so editing another workflow does not silently change what Start runs.
Groups, workflows, and steps display independent two-digit numbers that restart inside their direct
container. These labels are presentation-only: raw names, UUIDs, JSON data, and route references are
unchanged.
New steps start from only three guided categories: `检测`, `执行`, and `控制`. Conditions can later
switch capabilities or be combined in the guided AND/OR/NOT tree without changing the surrounding
policy and routes. Advanced JSON remains available for direct schema-level editing.

The three editor columns share one draggable splitter. Their widths are stored in
`settings.ui_layout.column_widths` only when the project is saved and restored on the next launch.
Without saved preferences, the workspace starts at `1723 × 1102` (clamped to the current screen)
with three-column proportions based on `249 / 259 / 1152`; saved local window dimensions and saved
project column widths still take precedence.
Every step card stays expanded by default, with its step name at the top followed by detection,
action, policy, and route summaries. Each configured route occupies its own line and shows its
result, count or variable predicate, and numbered group/workflow/step target; a step without explicit
routes describes the implicit success continuation and non-success termination. New window actions
and window-state conditions target an executable process name with optional ordered fallback names;
matching is case-insensitive and uses the executable basename. Minimize and restore affect every
visible top-level window owned by the selected process, while activate and move/resize choose one
window deterministically. Existing title-only configurations remain valid and editable through
advanced JSON. Window action fields remain on one row, showing geometry only for move/resize. The main-window
width and height are stored in local Windows application settings when the window closes successfully
and restored on the next launch; these local preferences do not dirty or modify the project JSON.
Step cards constrain themselves to the middle-column viewport: long route lines wrap within the
card, resizing the column recalculates card height, and the step list never uses horizontal scrolling.

Step properties open on a compact `常用配置` tab. Capability-specific advanced fields can be
revealed when needed, while the separate `高级 JSON` tab round-trips conditions, actions, policies,
and routes through the same validation path. Policy and route summaries use readable project names;
an unconditional route that would hide a later conditional route is rejected before save.
Common action, detection, policy, and route fields use a wrapping horizontal layout: controls stay
on one row while space permits and wrap only in narrower windows. Complex condition trees, action
sequences, and advanced policy hooks retain dedicated editing areas.
The action guide exposes registered action types as an exclusive wrapping button group; selecting a
button switches the same capability-specific form used when editing an existing action.

Visual condition forms can capture a region directly from a frozen desktop/window frame. Region
fields expose `框选区域`; image-template forms additionally expose `框选并截图`, which fills the
selected region and writes a PNG below `data/templates/` for recognition. Selection uses a
native-resolution overlay over the complete captured desktop or window: releasing the mouse
immediately completes a region, a single click completes a point, and Esc cancels. The local
`框选时隐藏程序界面` preference can hide Flow Runner before capture and is restored after success,
cancellation, or failure. This preference is remembered outside the project JSON and does not mark
the project as modified. On Windows, visible Flow Runner windows are excluded from screen capture
before they are hidden, preventing compositor animations from leaving a frozen or translucent copy
in the selection frame. Qt monitor model names are matched to Windows display-device names through
EDID aliases, with a guarded DPI-aware geometry fallback for drivers or virtual displays that do not
expose stable names.

The column controls support group/workflow/step editing, undo, validated save, settings, and explicit
parallel blocks. Parallel execution is never inferred from routes: create a parallel block and select
the workflows that should monitor concurrently. Children share task variables and runtime resources
while retaining separate workflow-local variables and call stacks.

Six common step templates cover OCR-and-click, OCR timeout continuation, delayed input, window
activation plus input, count-based workflow jumps, and success/timeout branches. Steps, workflows,
and groups can be copied with new UUIDs; references inside the copied scope are remapped while
external references remain unchanged. Existing parallel blocks can be edited, and a workflow cannot
be deleted while a named parallel block still depends on it. After confirmation, deleting any other
workflow atomically removes route rules that jump to, call, or count that workflow; deleting the
configured entry workflow selects the first remaining workflow, and one undo restores the complete
change.

The guided editor displays built-in capabilities, parameter names, choices, route outcomes, and
runtime states in Chinese while retaining stable English schema keys in advanced JSON. A single step
can freely mix and reorder mouse, keyboard, wait, variable, process, playback, and window actions;
the sequence list shows a readable summary rather than internal capability identifiers.
Normal result-binding selectors and summaries show Chinese condition and result names instead of
raw `$result...` syntax. Saving still writes the original stable binding expression, and unknown or
custom expressions remain available through the custom-expression mode.

Saving from the right-column control or with `Ctrl+S` first commits the currently edited condition, selected
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

The left and middle column controls provide start, pause/resume, stop, input recording,
selected-step execution, condition preview, and structured diagnostics. Packaged high-contrast
SVG assets provide the application/taskbar icon, command icons with their Chinese labels, and
persistent light-blue flow-tree expand/collapse arrows. Visual condition previews attach the recent
frame as an in-memory PNG without creating temporary screenshot files. Diagnostics include step
results, selected routes, frame/scene identifiers, retry data, errors, and resource wait events.
Collapsed workflow groups are remembered in local application settings, independently for each
project UUID. Refreshing or restarting restores those groups, newly created groups remain expanded,
and the parallel-monitor root is not included. Changing expansion state does not dirty or modify the
project JSON.

`设置 -> 启动流程后最小化` is a project-scoped setting and is off by default. When enabled, an
accepted toolbar or F6 start for a workflow or parallel block minimizes the window. Rejected starts,
selected-step execution, and condition preview do not minimize it. Completion and explicit stop do
not restore the window automatically.

A `system.wait` action displays a one-second, in-place countdown in the runtime log. F8
pause/resume freezes built-in condition and input checkpoints, waits, and recording playback, but
does not pause an independent input recording. The dedicated `暂停录制` / `继续录制` control works
with or without a running workflow and changes only the recording state. F7 cancels in-flight
runtime work, stops and saves an active or paused independent recording, and releases tracked held
keys and mouse buttons when the runtime terminates. Natural runtime completion leaves an independent
recording active. Atomic OS calls already in progress and processes already launched cannot be
reversed by pause or stop.

Default global hotkeys are F6 start, F7 stop, F8 workflow pause/resume, and F9 recording. The
`record_pause` hotkey defaults to empty (disabled) and can be configured in Settings. Saving hotkey
changes replaces the active listener and recording filter immediately; all five effective control
hotkeys (start, stop, workflow pause, recording toggle, and recording pause) are excluded from newly
recorded key events. A key removed from the control bindings becomes recordable immediately.

Each completed recording is preserved under
`data/recordings/recording_YYYYMMDD_HHMMSS.json` and also copied to
`data/recordings/latest.json` for stable playback references. A numeric suffix avoids overwriting a
recording saved in the same second. The icon-only folder control beside the recording pause control
opens the active project's recordings directory. The playback action can reuse a recording with
configurable speed and maximum gap.

Mouse actions support fixed or result-bound coordinates, an additional coordinate offset, click,
move, scroll, button-down, button-up, and drag operations. The guided mouse form exposes
`点选坐标` and an independent operation target. A fixed desktop point is stored as an absolute
screen coordinate; a fixed window point is stored relative to that target and is resolved from the
window's current origin each time the action runs. Dynamic `$result...position` bindings remain
absolute screen coordinates and never receive a second window-origin offset. Existing mouse JSON
without a target retains its absolute-desktop behavior. Keyboard actions support press, hotkey,
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
directory. Choosing a launch target in the guided form fills the executable, generated argument
prefix, and working directory automatically: `.py` uses the current global Python, `.pyw` prefers
the matching `pythonw.exe`, `.bat` uses `cmd.exe /c`, and normal executables run directly. Reselecting
a file replaces the previous generated prefix while preserving custom trailing arguments and a
manually customized working directory. Converted `.py` and `.pyw` helpers are hidden by default so
they cannot cover the game or steal visible screen space.

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

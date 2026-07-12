# Flow Runner Qt

Flow Runner Qt is a composable desktop-automation workflow editor and runtime for game
automation. The new implementation uses typed conditions, actions, policies, and routes instead
of fixed OCR/image step combinations.

## Requirements

- Python 3.11 or newer
- Windows for real desktop input, Win32 capture, and global-hotkey integration
- PaddleOCR-json or Tesseract when the corresponding OCR adapter is enabled

## Installation

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
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

```powershell
.\.venv\Scripts\python.exe -m flow_runner.app
# or, after installation
flow-runner
```

The default project path is `project.json` in the current directory. Visual styling is loaded
application-wide from `flow_runner/resources/styles/base.qss`; final visual design will be applied
from the user-provided `DESIGN.md` in a separate pass.

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

Relative executable paths are resolved from the directory containing `project.json`. The local
`PaddleOCR-json_v*/` folder is intentionally ignored by Git because it contains large third-party
binaries. Use `"ocr_engine": "tesseract"` to use the Tesseract adapter instead.

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

The main window uses a three-pane layout: groups/workflows on the left, steps in the center, and the
selected step's condition, actions, policies, and routes on the right. New steps start from only
three guided categories: `检测`, `执行`, and `控制`. Conditions can later switch capabilities or be
combined in the guided AND/OR/NOT tree without changing the surrounding policy and routes. Advanced
JSON remains available for direct schema-level editing.

The project toolbar supports group/workflow/step editing, undo, validated save, settings, and
explicit parallel blocks. Parallel execution is never inferred from routes: create a parallel block
and select the workflows that should monitor concurrently. Children share task variables and runtime
resources while retaining separate workflow-local variables and call stacks.

The runtime toolbar provides start, pause/resume, stop, input recording, selected-step execution,
condition preview, and structured diagnostics. Visual condition previews attach the recent frame as
an in-memory PNG without creating temporary screenshot files. Diagnostics include step results,
selected routes, frame/scene identifiers, retry data, errors, and resource wait events. Default global hotkeys are
F6 start, F7 stop, F8 pause/resume, and F9 recording; project settings can change or disable them.

Recordings are stored by default at `recordings/latest.json` beside the project. The playback action
can reuse a recording with configurable speed and maximum gap.

Mouse actions support fixed or result-bound coordinates, an additional coordinate offset, click,
move, scroll, button-down, button-up, and drag operations. Keyboard actions support press, hotkey,
text entry, key-down, and key-up. Text entry has three per-action modes: `keys` sends physical key
events and remains the default for game compatibility, `unicode` sends Windows Unicode input for
layout-independent Chinese or other text, and `clipboard` pastes text before restoring the previous
clipboard formats. Ordered step actions form input sequences without a separate sequence step type.
Long moves, drags, repeated keys, and interval text are divided into cancellable segments. Tracked
held inputs are released whenever a run terminates or the application shuts down; recording
playback also releases held keys on cancellation.

Program launch actions accept an optional `working_directory`. Normal launches pass it to the child
process and administrator launches pass it to `ShellExecuteW`; if omitted, normal launches inherit
the current directory and administrator launches use the executable directory.

## Persistence and safety

Project JSON, UUID references, registered condition/action configs, policy hooks, and runtime binding
syntax are validated on load and again before save. Saves write and validate a temporary sibling file, flush it,
rotate the five newest backups, and atomically replace the main file. Desktop/window interactions
are coordinated so read-only detection can share frames while conflicting input is serialized.
Screen-derived coordinates are revalidated under the exclusive interaction lease if another action
has changed the scene.

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

The legacy `flow_runner_p1.py`, `flow_runner_p2.py`, and `flow_runner_p3.py` files remain
reference-only during the refactor. The new package must not import them.

Generating a new project configuration from the legacy configuration and applying the future
`DESIGN.md` visual design are intentionally separate follow-up tasks requested by the user.

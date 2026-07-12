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
```

The default project path is `project.json` in the current directory. Visual styling is loaded
application-wide from `flow_runner/resources/styles/base.qss`; final visual design will be applied
from the user-provided `DESIGN.md` in a separate pass.

## Real Windows acceptance

Automated tests use fake capture, OCR, input, window, and process adapters. Before release, execute
every item in `REAL_ENVIRONMENT_CHECKLIST.md` on the target Windows/game environment. PaddleOCR-json
requires a client implementing the adapter protocol; Tesseract requires `pytesseract`, the Tesseract
executable, and the requested language data.

## Architecture

- `flow_runner/domain`: validated project, workflow, condition, action, policy, and routing models
- `flow_runner/engine`: Qt-independent execution, context, perception, and resource coordination
- `flow_runner/capabilities`: registered condition and action providers
- `flow_runner/infrastructure`: screenshot, OCR, input, persistence, and logging adapters
- `flow_runner/ui`: PySide6 views, ViewModels, dialogs, and application-wide QSS management

The legacy `flow_runner_p1.py`, `flow_runner_p2.py`, and `flow_runner_p3.py` files remain
reference-only during the refactor. The new package must not import them.

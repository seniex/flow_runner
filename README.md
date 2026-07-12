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

## Architecture

- `flow_runner/domain`: validated project, workflow, condition, action, policy, and routing models
- `flow_runner/engine`: Qt-independent execution, context, perception, and resource coordination
- `flow_runner/capabilities`: registered condition and action providers
- `flow_runner/infrastructure`: screenshot, OCR, input, persistence, and logging adapters
- `flow_runner/ui`: PySide6 views, ViewModels, dialogs, and application-wide QSS management

The legacy `flow_runner_p1.py`, `flow_runner_p2.py`, and `flow_runner_p3.py` files remain
reference-only during the refactor. The new package must not import them.

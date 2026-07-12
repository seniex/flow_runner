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

OCR engine selection is stored in the project `settings` object. PaddleOCR-json v1.4.x uses its
stdin/stdout JSON protocol and is started lazily on the first OCR request:

```json
{
  "settings": {
    "ocr_engine": "paddle",
    "paddle_exe_path": "PaddleOCR-json_v1.4.1/PaddleOCR-json.exe"
  }
}
```

Relative executable paths are resolved from the directory containing `project.json`. The local
`PaddleOCR-json_v*/` folder is intentionally ignored by Git because it contains large third-party
binaries. Use `"ocr_engine": "tesseract"` to use the Tesseract adapter instead.

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

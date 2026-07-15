# Flow Runner Windows Double-Click Launcher Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a root-level `.pyw` launcher that starts Flow Runner from the correct working directory without a console and reports startup failures visibly and in `data/launcher_error.log`.

**Architecture:** Keep the launcher as a thin wrapper around `flow_runner.app.main()`. Expose small functions for root resolution, application launch, and error reporting so unit tests can import the `.pyw` file without opening the GUI.

**Tech Stack:** Python 3.12, Windows `pythonw.exe`, `ctypes`/User32, pathlib, pytest, Ruff.

---

### Task 1: Define Launcher Behavior with Failing Tests

**Files:**
- Create: `tests/unit/test_windows_launcher.py`
- Read: `flow_runner/app.py`

- [x] **Step 1: Add the dynamic launcher loader and working-directory test**

Create `tests/unit/test_windows_launcher.py` with:

```python
from importlib.machinery import SourceFileLoader
from importlib.util import module_from_spec, spec_from_loader
from pathlib import Path
from types import ModuleType


def _launcher() -> ModuleType:
    path = Path("start_flow_runner.pyw").resolve()
    loader = SourceFileLoader("start_flow_runner", str(path))
    spec = spec_from_loader(loader.name, loader)
    if spec is None:
        raise RuntimeError("could not create launcher module spec")
    module = module_from_spec(spec)
    loader.exec_module(module)
    return module


def test_launcher_runs_application_from_project_root(monkeypatch, tmp_path):
    launcher = _launcher()
    observed: list[Path] = []
    expected_root = Path("start_flow_runner.pyw").resolve().parent

    def fake_main() -> int:
        observed.append(Path.cwd())
        return 17

    monkeypatch.setattr("flow_runner.app.main", fake_main)
    monkeypatch.chdir(tmp_path)

    result = launcher.run_application()

    assert result == 17
    assert observed == [expected_root]
```

- [x] **Step 2: Add error-log and log-write-failure tests**

Append:

```python
def test_launcher_reports_traceback_to_data_log(monkeypatch, tmp_path):
    launcher = _launcher()
    messages: list[str] = []
    monkeypatch.setattr(launcher, "_show_error_message", messages.append)

    try:
        raise RuntimeError("launcher boom")
    except RuntimeError as error:
        launcher.report_startup_error(error, tmp_path)

    log_path = tmp_path / "data" / "launcher_error.log"
    content = log_path.read_text(encoding="utf-8")
    assert "RuntimeError: launcher boom" in content
    assert "Traceback" in content
    assert str(log_path) in messages[0]


def test_launcher_still_shows_error_when_log_cannot_be_written(monkeypatch, tmp_path):
    launcher = _launcher()
    messages: list[str] = []
    monkeypatch.setattr(launcher, "_show_error_message", messages.append)
    invalid_root = tmp_path / "not-a-directory"
    invalid_root.write_text("occupied", encoding="utf-8")

    launcher.report_startup_error(RuntimeError("launcher boom"), invalid_root)

    assert "RuntimeError: launcher boom" in messages[0]
    assert "无法写入错误日志" in messages[0]
```

- [x] **Step 3: Run the tests and verify RED**

Run:

```powershell
python -m pytest -q tests/unit/test_windows_launcher.py
```

Expected: test collection or all three tests fail because `start_flow_runner.pyw` does not exist.

---

### Task 2: Implement the Root `.pyw` Launcher

**Files:**
- Create: `start_flow_runner.pyw`
- Test: `tests/unit/test_windows_launcher.py`

- [x] **Step 1: Create the launcher implementation**

Create `start_flow_runner.pyw` with:

```python
from __future__ import annotations

import ctypes
import os
import traceback
from pathlib import Path


def application_root() -> Path:
    return Path(__file__).resolve().parent


def run_application() -> int:
    os.chdir(application_root())
    from flow_runner.app import main

    return main()


def report_startup_error(error: Exception, root: Path | None = None) -> None:
    base = root or application_root()
    log_path = base / "data" / "launcher_error.log"
    log_failure: OSError | None = None
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            "".join(traceback.format_exception(type(error), error, error.__traceback__)),
            encoding="utf-8",
        )
    except OSError as write_error:
        log_failure = write_error

    message = f"{type(error).__name__}: {error}\n\n"
    if log_failure is None:
        message += f"详细信息已写入：\n{log_path}"
    else:
        message += f"无法写入错误日志：{log_failure}"
    _show_error_message(message)


def _show_error_message(message: str) -> None:
    ctypes.windll.user32.MessageBoxW(None, message, "Flow Runner 启动失败", 0x10)


if __name__ == "__main__":
    try:
        raise SystemExit(run_application())
    except Exception as error:
        report_startup_error(error)
        raise SystemExit(1) from error
```

- [x] **Step 2: Run the focused tests and verify GREEN**

Run:

```powershell
python -m pytest -q tests/unit/test_windows_launcher.py
```

Expected: 3 tests pass without opening a GUI.

- [x] **Step 3: Run launcher lint and format checks**

Run:

```powershell
python -m ruff check start_flow_runner.pyw tests/unit/test_windows_launcher.py
python -m ruff format --check start_flow_runner.pyw tests/unit/test_windows_launcher.py
```

Expected: both commands exit 0.

---

### Task 3: Document Double-Click Startup

**Files:**
- Modify: `README.md:58-82`

- [x] **Step 1: Add the Windows double-click subsection**

Insert this exact content after the `flow-runner` code block and before the paragraph beginning `All three commands`:

```markdown
Windows double-click launcher:

- Double-click `start_flow_runner.pyw` in the project root.
- This uses the global `pythonw.exe` associated with `.pyw` files, so install the project with the global Python method first.
- It loads `data/project.json` without opening a console window.
- Startup failures show an error dialog and write details to `data/launcher_error.log`.
```

- [x] **Step 2: Verify documentation matches implementation**

Run:

```powershell
rg -n 'start_flow_runner\.pyw|global `pythonw\.exe`|data/project\.json|data/launcher_error\.log' README.md
```

Expected: all four launcher statements appear in the Running section.

---

### Task 4: Full Verification, Commit, and Push

**Files:**
- Include: `start_flow_runner.pyw`
- Include: `tests/unit/test_windows_launcher.py`
- Include: `README.md`
- Include: `docs/superpowers/plans/2026-07-15-windows-pyw-launcher.md`

- [x] **Step 1: Run focused and full verification**

Run:

```powershell
python -m pytest -q tests/unit/test_windows_launcher.py tests/unit/test_package.py
$env:QT_QPA_PLATFORM='offscreen'
python -m pytest -q
python -m ruff check flow_runner tests scripts start_flow_runner.pyw
python -m ruff format --check flow_runner tests scripts start_flow_runner.pyw
python -m mypy flow_runner
python -m compileall -q flow_runner
python -m pip check
git diff --check
```

Expected: 5 focused tests pass, the full suite passes, and every static check exits 0.

- [x] **Step 2: Review and commit**

Run:

```powershell
git status --short
git diff -- start_flow_runner.pyw tests/unit/test_windows_launcher.py README.md docs/superpowers/plans/2026-07-15-windows-pyw-launcher.md
git add start_flow_runner.pyw tests/unit/test_windows_launcher.py README.md docs/superpowers/plans/2026-07-15-windows-pyw-launcher.md
git diff --cached --check
git commit -m "feat: add Windows double-click launcher"
```

Expected: commit succeeds and includes only the launcher implementation, tests, README, and implementation plan. The design-spec commit remains earlier in history.

- [x] **Step 3: Push and verify remote state**

Run:

```powershell
git push origin feature-region-picker-dark-ui
git rev-parse HEAD
git rev-parse origin/feature-region-picker-dark-ui
git status --short --branch
```

Expected: local and remote-tracking SHAs match and the working tree is clean.

# Flow Runner Release Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining repository, release-build, documentation, and real-Windows acceptance work without interrupting the user's daily desktop activity without advance notice.

**Architecture:** Treat the current `main` commit as the verified functional baseline and execute completion work in the isolated `chore/release-completion` worktree. Non-interactive checks run first. UAC, global-hotkey, DPI, multi-monitor, real-input, dependency-installation, and visible-GUI tests are hard-gated by a user notice and confirmation before execution.

**Tech Stack:** Python 3.12, PySide6, pytest/pytest-qt, Ruff, mypy, pip/hatchling wheel builds, PowerShell, Windows 10 real-environment acceptance.

---

## File Map

- Create: `docs/superpowers/plans/2026-07-14-flow-runner-release-completion.md` — authoritative execution checklist and user-impact gates.
- Modify: `REFACTOR_STATUS.md` — current branch/date, automated evidence, release-build evidence, and remaining acceptance state.
- Modify: `REAL_ENVIRONMENT_CHECKLIST.md` — current automated baseline plus PASS/FAIL/BLOCKED evidence for each real-environment item.
- Modify only if required by a discovered defect: the focused `flow_runner/` module and its matching `tests/` file.
- Do not modify, delete, move, or stage: root `Screenshot 2026-07-13 032847.png` and `project.1783952247966102600.bak.json` unless the user gives a separate artifact-retention decision.
- Do not implement final visual styling until a user-provided root `DESIGN.md` exists and its direction is approved.

### Task 1: Establish the isolated verified baseline

**Files:**
- No tracked file changes.
- Environment: `.worktrees/release-completion/.venv/`

- [x] **Step 1: Create the isolated worktree**

Run from the repository root:

```powershell
git check-ignore -q .worktrees
git worktree add .worktrees\release-completion -b chore/release-completion
```

Expected: worktree created from `21f2f7d` on `chore/release-completion`.

- [x] **Step 2: Create the test environment**

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[test]"
```

Expected: editable `flow-runner-qt==0.1.0` and all test dependencies install successfully.

- [x] **Step 3: Verify the baseline**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check flow_runner tests
.\.venv\Scripts\python.exe -m ruff format --check flow_runner tests
.\.venv\Scripts\python.exe -m mypy flow_runner
.\.venv\Scripts\python.exe -m pip check
```

Expected: `244 passed`, Ruff clean, `122 files already formatted`, mypy clean for `99 source files`, and no broken requirements.

- [x] **Step 4: Commit the reviewed plan**

```powershell
git add docs/superpowers/plans/2026-07-14-flow-runner-release-completion.md
git commit -m "docs: plan Flow Runner release completion"
```

Expected: one documentation-only commit; no user-owned root artifact is staged.

### Task 2: Build and inspect the current release wheel

**Files:**
- Generated, ignored: `dist/flow_runner_qt-0.1.0-py3-none-any.whl`
- Modify after evidence exists: `REFACTOR_STATUS.md`

- [x] **Step 1: Remove only the isolated worktree's old build output**

```powershell
$dist = (Join-Path (Get-Location) 'dist')
if (Test-Path -LiteralPath $dist) {
    $resolved = (Resolve-Path -LiteralPath $dist).Path
    if ($resolved -ne $dist) { throw "Unexpected dist path: $resolved" }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
```

Expected: `dist/` is absent before the build. Do not touch any path outside this worktree.

- [x] **Step 2: Build the wheel without dependencies**

```powershell
.\.venv\Scripts\python.exe -m pip wheel . --no-deps --wheel-dir dist
```

Expected: exactly one `flow_runner_qt-0.1.0-py3-none-any.whl` in `dist/`.

- [x] **Step 3: Inspect required wheel contents and hash**

```powershell
$wheel = Get-ChildItem -LiteralPath dist -Filter 'flow_runner_qt-0.1.0-*.whl' -File
if ($wheel.Count -ne 1) { throw "Expected one wheel, found $($wheel.Count)" }
.\.venv\Scripts\python.exe -c "import sys,zipfile; p=sys.argv[1]; names=set(zipfile.ZipFile(p).namelist()); required={'flow_runner/app.py','flow_runner/resources/styles/base.qss','flow_runner/ui/localization.py','flow_runner/infrastructure/input/mouse.py','flow_runner/migration/legacy.py'}; missing=required-names; assert not missing, missing; print(len(names))" $wheel.FullName
Get-FileHash -Algorithm SHA256 -LiteralPath $wheel.FullName
```

Expected: no missing required files, a printed entry count, and one SHA-256 value recorded for documentation.

- [x] **Step 4: Perform a clean-environment import and offscreen application smoke test**

```powershell
$wheel = Get-ChildItem -LiteralPath dist -Filter 'flow_runner_qt-0.1.0-*.whl' -File
if ($wheel.Count -ne 1) { throw "Expected one wheel, found $($wheel.Count)" }
$smoke = Join-Path $env:TEMP 'flow_runner_release_smoke_20260714'
if (Test-Path -LiteralPath $smoke) { Remove-Item -LiteralPath $smoke -Recurse -Force }
python -m venv $smoke
& "$smoke\Scripts\python.exe" -m pip install $wheel.FullName
$env:QT_QPA_PLATFORM='offscreen'
& "$smoke\Scripts\python.exe" -c "import tempfile; from pathlib import Path; from flow_runner.app import create_application; from flow_runner.domain.project import Project; from flow_runner.infrastructure.persistence.project_store import ProjectStore; root=Path(tempfile.mkdtemp()); path=root/'project.json'; ProjectStore(path).save(Project(name='release-smoke')); composition=create_application([], project_path=path); assert composition.window.view_model.project.name=='release-smoke'; composition.window.close(); composition.app.quit(); print('release smoke ok')"
```

Expected: `release smoke ok`. This uses Qt offscreen and does not show a window or send desktop input.

### Task 3: Calibrate repository and acceptance documentation

**Files:**
- Modify: `REFACTOR_STATUS.md`
- Modify: `REAL_ENVIRONMENT_CHECKLIST.md`

- [x] **Step 1: Update the status header and automated evidence**

Apply these exact factual changes to `REFACTOR_STATUS.md`:

```text
更新日期：2026-07-14
分支：main（后续收尾在 chore/release-completion）
# 244 passed
# Success: no issues found in 99 source files
```

Replace the old wheel hash/count sentence with the entry count and SHA-256 produced by Task 2. Do not reuse the earlier pre-fix wheel hash.

- [x] **Step 2: Update the real-environment automated baseline**

Replace the stale baseline paragraph in `REAL_ENVIRONMENT_CHECKLIST.md` with:

```text
自动化基线（2026-07-14）：`244 passed`，Ruff、格式检查、严格 mypy（99 个源文件）、`pip check` 和最新 wheel 构建/干净安装冒烟均通过。此结果不替代下列真实桌面/游戏环境验收。
```

- [x] **Step 3: Record artifact-retention state without changing user files**

Add a short repository note to `REFACTOR_STATUS.md` stating that the root screenshot and `project.1783952247966102600.bak.json` remain user-owned untracked evidence and were intentionally not staged, moved, or deleted.

- [x] **Step 4: Verify documentation consistency**

```powershell
rg -n "213 passed|98 source files|refactor/pyside6-workflow|4BC641A5036B3EEC027D50D72CA48C253DD8A3827C4A742031C6BC384B86390C" REFACTOR_STATUS.md REAL_ENVIRONMENT_CHECKLIST.md
git diff --check
```

Expected: no stale baseline, source-count, old branch, or old wheel-hash matches; `git diff --check` exits successfully.

- [x] **Step 5: Commit the calibrated automated and build evidence**

```powershell
git add REFACTOR_STATUS.md REAL_ENVIRONMENT_CHECKLIST.md
git commit -m "docs: refresh release verification evidence"
```

Expected: one documentation-only commit containing the fresh wheel and automated baseline evidence.

### Task 4: Perform the non-interactive environment audit

**Files:**
- Modify only with new evidence: `REAL_ENVIRONMENT_CHECKLIST.md`

- [ ] **Step 1: Audit display topology and DPI without changing settings**

```powershell
.\.venv\Scripts\python.exe -c "from PySide6.QtGui import QGuiApplication; app=QGuiApplication([]); print([(s.name(), s.geometry().getRect(), s.devicePixelRatio()) for s in app.screens()]); app.quit()"
```

Expected on the current host: one screen. Keep multi-monitor acceptance `BLOCKED` if no second screen is present. This step must not change display settings.

- [ ] **Step 2: Audit Tesseract availability without installing anything**

```powershell
$command = Get-Command tesseract -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m pip show pytesseract
if ($command) { & $command.Source --version }
```

Expected on the current host until external state changes: Tesseract command and `pytesseract` are absent; retain `BLOCKED` with fresh date/evidence.

- [ ] **Step 3: Audit potentially conflicting legacy hotkey processes without stopping them**

```powershell
Get-CimInstance Win32_Process |
    Where-Object { $_.Name -match 'python|BgOcrClick' -or $_.CommandLine -match 'BgOcrClick|flow_runner_p[123]' } |
    Select-Object ProcessId,Name,CommandLine
```

Expected: evidence only. Do not terminate a process and do not send F6-F9 in this task.

- [ ] **Step 4: Update only facts proven by the audit**

Record the date, detected screen count/DPI ratio, Tesseract availability, and legacy-process state. Leave tests requiring a state change as `BLOCKED`.

- [ ] **Step 5: Commit the non-interactive audit evidence**

If Task 4 changed `REAL_ENVIRONMENT_CHECKLIST.md`, run:

```powershell
git add REAL_ENVIRONMENT_CHECKLIST.md
git commit -m "docs: refresh Windows acceptance blockers"
```

Expected: the commit contains evidence only and no claim that a blocked interactive test passed.

### Task 5: User-impact acceptance gates

**Files:**
- Modify after each approved test: `REAL_ENVIRONMENT_CHECKLIST.md`

- [ ] **Step 1: Notify and wait before the global-hotkey test**

Send the user this notice before doing anything else in this step:

```text
准备进行全局热键实机验收。测试会启动 Flow Runner、切换到其它窗口，并发送 F6、F8、F7、F9；这些按键可能触发旧版挂机程序或影响当前游戏。请先保存工作并关闭旧 BgOcrClick。你回复“可以测试热键”后我再执行。
```

Do not start the app, stop processes, focus windows, or send keys before that exact confirmation.

- [ ] **Step 2: Execute the approved hotkey test**

After confirmation, use the `computer-use` skill for visible-window focus changes and key sending. Verify start, pause, resume, stop, and recording exactly once each from a non-Flow-Runner foreground window. Stop immediately if another application responds to F6-F9.

Expected: PASS evidence includes timestamped runtime events and no duplicate trigger. Otherwise record FAIL/BLOCKED with the observed conflicting process/window.

- [ ] **Step 3: Notify and wait before the administrator-launch test**

Send the user this notice:

```text
准备进行管理员启动验收。测试会触发一次 Windows UAC 提示，并启动一个只写入临时结果文件的隐藏 cmd.exe；不会修改系统配置。请在方便处理 UAC 弹窗时回复“可以测试管理员启动”。
```

Do not invoke `ShellExecuteW(..., "runas", ...)` before confirmation.

- [ ] **Step 4: Execute the approved administrator-launch test**

Use `WindowsProcessLauncher` with `run_as_admin=True`, an explicit temporary working directory, and `hide_window=True`. The child command must write its working directory and administrator token result under `%TEMP%\flow_runner_admin_acceptance`; poll for the result with a bounded timeout and delete only the temporary acceptance directory after its contents are recorded.

Expected: one UAC prompt, correct working directory, elevated token evidence, no visible console, and a PASS entry. If UAC is declined, record BLOCKED rather than retrying automatically.

- [ ] **Step 5: Notify and wait before DPI changes**

Send the user this notice:

```text
准备进行 DPI 100%/125%/150% 验收。该测试需要你切换 Windows 显示缩放，桌面布局和应用尺寸会暂时变化，部分应用可能要求注销。请保存工作；回复“可以测试 DPI”后，我会逐档提示你切换并在每档完成截图、框选和点击坐标验证。
```

Do not change display scaling automatically. The user performs each settings change; the agent only tests after the user confirms the new scale is active.

- [ ] **Step 6: Handle multi-monitor acceptance**

If Task 4 still detects one screen, retain `BLOCKED` and state that a second physical/virtual display is required. If the user later provides two screens, notify before moving windows or the pointer across displays, then test screen origins, negative coordinates, capture regions, and clicks.

- [ ] **Step 7: Notify before Tesseract installation**

If Tesseract remains absent, ask whether the user wants the optional engine installed. State that installation changes the machine and downloads an executable/language data. Do not install through `winget`, Chocolatey, an installer, or pip until the user confirms.

- [ ] **Step 8: Commit approved real-environment evidence**

After each approved acceptance batch, verify the recorded result and run:

```powershell
git add REAL_ENVIRONMENT_CHECKLIST.md REFACTOR_STATUS.md
git commit -m "docs: record approved Windows acceptance results"
```

Expected: only tests actually executed after user confirmation are changed from `BLOCKED` to `PASS` or `FAIL`.

### Task 6: Final visual-design gate

**Files:**
- Required user input: root `DESIGN.md`
- Potential later modifications: `flow_runner/resources/styles/base.qss`, `flow_runner/resources/icons/`, UI semantic object names only when required by the approved design.

- [ ] **Step 1: Check for the design specification**

```powershell
Test-Path -LiteralPath DESIGN.md
```

Expected now: `False`.

- [ ] **Step 2: Keep visual design explicitly deferred**

Do not invent a visual direction. Record that final styling remains blocked on the user-provided `DESIGN.md`. When it arrives, run a separate brainstorming/spec/plan cycle and obtain visual-direction confirmation before modifying QSS or assets.

### Task 7: Final verification and integration handoff

**Files:**
- Modify: `REFACTOR_STATUS.md`
- Modify: `REAL_ENVIRONMENT_CHECKLIST.md`
- Plan: `docs/superpowers/plans/2026-07-14-flow-runner-release-completion.md`

- [ ] **Step 1: Run final non-interactive verification**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check flow_runner tests
.\.venv\Scripts\python.exe -m ruff format --check flow_runner tests
.\.venv\Scripts\python.exe -m mypy flow_runner
.\.venv\Scripts\python.exe -m pip check
git diff --check
```

Expected: all checks pass with the current documented counts.

- [ ] **Step 2: Review final repository scope**

```powershell
git status --short
git diff --stat
git diff
```

Expected: only the plan and evidence/status documents are tracked changes unless an approved acceptance test exposed and fixed a real defect. The root screenshot and backup remain outside this worktree and untouched.

- [ ] **Step 3: Request code review and resolve findings**

Use `superpowers:requesting-code-review` for the final tracked diff. Fix every Critical/Important finding with a failing test first when code behavior changes.

- [ ] **Step 4: Complete the branch**

Use `superpowers:finishing-a-development-branch`. Present merge/PR/keep/discard choices. Do not push `main`, create a tag, or publish a release without an explicit integration choice from the user.

## Completion Rules

- The non-interactive repository/build/documentation tasks are complete only with fresh command evidence.
- A user-impact test is complete only after advance notice, explicit confirmation, execution, and recorded evidence.
- A test may remain `BLOCKED` only when the required hardware, dependency, user-controlled setting, or conflict resolution is unavailable; do not convert BLOCKED to PASS based on automated tests.
- Final visual design remains outside this plan until `DESIGN.md` exists.
- The project may be described as functionally implemented while real-environment acceptance remains incomplete; do not claim full release acceptance until every required checklist item is PASS or the user explicitly changes the release criteria.

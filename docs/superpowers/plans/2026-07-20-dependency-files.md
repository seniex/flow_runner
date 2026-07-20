# Dependency Files Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add runtime and development requirements files plus a Chinese guide that accurately documents all Python and external dependencies.

**Architecture:** Keep `pyproject.toml` as the package metadata source of truth. Mirror its runtime dependency ranges in `requirements.txt`; make `requirements-dev.txt` include that file and append the test extra. Document responsibilities, platform markers, installation commands, and OCR external components in `docs/DEPENDENCIES.md`.

**Tech Stack:** pip requirements syntax, Python packaging metadata, Markdown.

---

### Task 1: Create Requirements Files

**Files:**
- Create: `requirements.txt`
- Create: `requirements-dev.txt`

- [ ] **Step 1: Mirror runtime dependencies**

Copy the nine entries from `[project].dependencies` in `pyproject.toml` without changing version ranges. Preserve the Windows markers on `pywin32` and `windows-capture`.

- [ ] **Step 2: Add development overlay**

Start `requirements-dev.txt` with `-r requirements.txt`, then add the six entries from `[project.optional-dependencies].test`.

### Task 2: Write Dependency Guide

**Files:**
- Create: `docs/DEPENDENCIES.md`

- [ ] **Step 1: Document installation**

Include virtual-environment commands for runtime-only and development installs, plus the existing `pyproject.toml` editable-install alternative.

- [ ] **Step 2: Document dependency responsibilities**

Use tables to explain PySide6, Pydantic, Pillow, OpenCV, NumPy, PyAutoGUI, pynput, pywin32, and windows-capture, distinguishing Windows-only packages.

- [ ] **Step 3: Document OCR and maintenance rules**

Explain that `pytesseract`, the Tesseract executable/language data, and PaddleOCR-json are external optional components, and state that dependency ranges should be synchronized with `pyproject.toml`.

### Task 3: Verify

**Files:**
- Verify: `pyproject.toml`, `requirements.txt`, `requirements-dev.txt`, `docs/DEPENDENCIES.md`

- [ ] **Step 1: Check content parity**

Compare each requirements entry against the corresponding project or test extra entry.

- [ ] **Step 2: Parse requirements**

Run `python -m pip install --dry-run -r requirements.txt` and `python -m pip install --dry-run -r requirements-dev.txt` when supported by the installed pip; otherwise run `python -m pip check` and report the limitation.

- [ ] **Step 3: Check final diff**

Run `git diff --check` and `git status --short`; confirm the pre-existing `data/project.json` and image changes remain untouched.

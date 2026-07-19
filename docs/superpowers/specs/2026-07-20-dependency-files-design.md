# Dependency Files Design

## Goal

Add conventional pip requirements files and a Chinese dependency guide without changing runtime
behavior or the dependency ranges already declared in `pyproject.toml`.

## Approaches Considered

1. Put runtime and development packages in one `requirements.txt`. This is simple, but installs
   test and quality tools in runtime environments.
2. Make requirements files contain only editable project references such as `-e .[test]`. This
   avoids duplication, but is less useful to readers and tools expecting explicit package entries.
3. Mirror explicit runtime dependencies in `requirements.txt`, include that file from
   `requirements-dev.txt`, and add development dependencies there. This keeps installation
   conventional and separates runtime from development concerns.

Approach 3 is selected.

## Files

- `requirements.txt` mirrors `[project].dependencies` from `pyproject.toml`, including Windows
  environment markers.
- `requirements-dev.txt` starts with `-r requirements.txt` and mirrors
  `[project.optional-dependencies].test`.
- `docs/DEPENDENCIES.md` explains each dependency's role, installation commands, Windows-specific
  packages, optional OCR components, and the synchronization rule.

`pyproject.toml` remains the package metadata source of truth. When dependency versions change,
the matching requirements file must be updated in the same change.

## Optional External Components

`pytesseract`, the Tesseract executable, Tesseract language data, and PaddleOCR-json remain outside
the required dependency files. The guide will explain when they are needed and how they differ
from normal Python runtime dependencies.

## Verification

- Compare every requirements entry and version range against `pyproject.toml`.
- Parse both requirements files with pip using a dry-run when supported by the installed pip.
- Run `git diff --check` and inspect the final diff to ensure only the intended documentation and
  dependency files changed.

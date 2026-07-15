from datetime import datetime
from pathlib import Path

_INVALID_FILENAME_CHARACTERS = frozenset('<>:"/\\|?*')


def session_log_path(
    directory: Path,
    project_name: str,
    started_at: datetime,
    *,
    debug: bool,
) -> Path:
    safe = "".join(
        "_" if character in _INVALID_FILENAME_CHARACTERS else character
        for character in project_name
    )
    safe = safe.strip().rstrip(" ._") or "FlowRunner"
    directory.mkdir(parents=True, exist_ok=True)
    mode = "debug" if debug else "normal"
    stem = f"{safe}_{started_at:%Y%m%d_%H%M%S}_{mode}"
    candidate = directory / f"{stem}.log"
    suffix = 2
    while candidate.exists():
        candidate = directory / f"{stem}_{suffix}.log"
        suffix += 1
    candidate.touch(exist_ok=False)
    return candidate

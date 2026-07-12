import csv
import io
import subprocess
from collections.abc import Callable
from typing import Protocol


class ProcessQuery(Protocol):
    def exists(self, name: str) -> bool: ...


class WindowsProcessQuery:
    def __init__(self, run_tasklist: Callable[[], str] | None = None) -> None:
        self.run_tasklist = run_tasklist or _run_tasklist

    def exists(self, name: str) -> bool:
        expected = name.casefold()
        rows = csv.reader(io.StringIO(self.run_tasklist()))
        return any(row and row[0].strip().casefold() == expected for row in rows)


def _run_tasklist() -> str:
    completed = subprocess.run(
        ["tasklist", "/FO", "CSV", "/NH"],
        check=True,
        capture_output=True,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    return completed.stdout

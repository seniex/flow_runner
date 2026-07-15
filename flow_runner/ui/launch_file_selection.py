import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class LaunchFileSelection:
    path: Path
    arguments: tuple[str, ...]
    working_directory: Path


def launch_file_selection(
    selected: Path,
    *,
    python_executable: Path,
    comspec: Path,
) -> LaunchFileSelection:
    selected = selected.resolve()
    python_executable = python_executable.resolve()
    comspec = comspec.resolve()
    suffix = selected.suffix.casefold()
    if suffix == ".py":
        return LaunchFileSelection(
            python_executable,
            (str(selected),),
            selected.parent,
        )
    if suffix == ".pyw":
        pythonw = python_executable.with_name("pythonw.exe")
        executable = pythonw if pythonw.is_file() else python_executable
        return LaunchFileSelection(executable, (str(selected),), selected.parent)
    if suffix == ".bat":
        return LaunchFileSelection(
            comspec,
            ("/c", str(selected)),
            selected.parent,
        )
    return LaunchFileSelection(selected, (), selected.parent)


def replace_automatic_prefix(
    current: list[str],
    previous: tuple[str, ...],
    replacement: tuple[str, ...],
) -> list[str]:
    custom = current[len(previous) :] if tuple(current[: len(previous)]) == previous else current
    return [*replacement, *custom]


def infer_automatic_prefix(path: Path, arguments: list[str]) -> tuple[str, ...]:
    name = path.name.casefold()
    if name in {"python.exe", "pythonw.exe", "python", "pythonw"} and arguments:
        if Path(arguments[0]).suffix.casefold() in {".py", ".pyw"}:
            return (arguments[0],)
    if name in {"cmd.exe", "cmd"} and len(arguments) >= 2:
        if arguments[0].casefold() == "/c" and Path(arguments[1]).suffix.casefold() == ".bat":
            return arguments[0], arguments[1]
    return ()


def default_python_executable() -> Path:
    return Path(sys.executable).resolve()


def default_comspec(environment: Mapping[str, str] = os.environ) -> Path:
    configured = Path(environment.get("COMSPEC", ""))
    if configured.is_file():
        return configured.resolve()
    return Path(environment.get("SystemRoot", r"C:\Windows")) / "System32" / "cmd.exe"

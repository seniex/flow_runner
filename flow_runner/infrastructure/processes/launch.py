import asyncio
import ctypes
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol


class PopenCallable(Protocol):
    def __call__(
        self,
        command: list[str],
        *,
        cwd: Path | None,
        hide_window: bool,
    ) -> Any: ...


ShellExecuteCallable = Callable[[Path, str, Path, bool], Any]


class WindowsProcessLauncher:
    def __init__(
        self,
        *,
        popen: PopenCallable | None = None,
        shell_execute: ShellExecuteCallable | None = None,
    ) -> None:
        self.popen = popen or _popen
        self.shell_execute = shell_execute or _shell_execute_admin

    async def __call__(
        self,
        path: Path,
        arguments: tuple[str, ...],
        run_as_admin: bool,
        working_directory: Path | None,
        hide_window: bool,
    ) -> None:
        if run_as_admin:
            await asyncio.to_thread(
                self.shell_execute,
                path,
                subprocess.list2cmdline(arguments),
                working_directory or path.parent,
                hide_window,
            )
        else:
            await asyncio.to_thread(
                self.popen,
                [str(path), *arguments],
                cwd=working_directory,
                hide_window=hide_window,
            )


def _shell_execute_admin(
    path: Path,
    arguments: str,
    working_directory: Path,
    hide_window: bool,
) -> None:
    result = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", str(path), arguments, str(working_directory), 0 if hide_window else 1
    )
    if result <= 32:
        raise OSError(f"ShellExecuteW failed with code {result}")


def _popen(command: list[str], *, cwd: Path | None, hide_window: bool) -> Any:
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if hide_window else 0
    return subprocess.Popen(command, cwd=cwd, creationflags=creationflags)

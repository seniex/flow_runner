import asyncio
import ctypes
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

PopenCallable = Callable[[list[str]], Any]
ShellExecuteCallable = Callable[[Path, str], Any]


class WindowsProcessLauncher:
    def __init__(
        self,
        *,
        popen: PopenCallable = subprocess.Popen,
        shell_execute: ShellExecuteCallable | None = None,
    ) -> None:
        self.popen = popen
        self.shell_execute = shell_execute or _shell_execute_admin

    async def __call__(
        self,
        path: Path,
        arguments: tuple[str, ...],
        run_as_admin: bool,
    ) -> None:
        if run_as_admin:
            await asyncio.to_thread(self.shell_execute, path, subprocess.list2cmdline(arguments))
        else:
            await asyncio.to_thread(self.popen, [str(path), *arguments])


def _shell_execute_admin(path: Path, arguments: str) -> None:
    result = ctypes.windll.shell32.ShellExecuteW(
        None, "runas", str(path), arguments, str(path.parent), 1
    )
    if result <= 32:
        raise OSError(f"ShellExecuteW failed with code {result}")

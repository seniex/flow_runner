import asyncio
import importlib
from typing import Any, Protocol


class WindowQuery(Protocol):
    def query(self, title: str) -> dict[str, Any]: ...


class WindowController(Protocol):
    async def activate(self, title: str) -> None: ...
    async def minimize(self, title: str) -> None: ...
    async def restore(self, title: str) -> None: ...
    async def move_resize(self, title: str, geometry: tuple[int, int, int, int]) -> None: ...


class Win32WindowQuery:
    def __init__(self, backend: Any | None = None) -> None:
        self.backend = backend or _PyWin32WindowBackend()

    def query(self, title: str) -> dict[str, Any]:
        return dict(self.backend.query(title))


class Win32WindowController:
    def __init__(self, backend: Any | None = None) -> None:
        self.backend = backend or _PyWin32WindowBackend()

    async def activate(self, title: str) -> None:
        await asyncio.to_thread(self.backend.activate, title)

    async def minimize(self, title: str) -> None:
        await asyncio.to_thread(self.backend.minimize, title)

    async def restore(self, title: str) -> None:
        await asyncio.to_thread(self.backend.restore, title)

    async def move_resize(self, title: str, geometry: tuple[int, int, int, int]) -> None:
        await asyncio.to_thread(self.backend.move_resize, title, geometry)


class _PyWin32WindowBackend:
    def __init__(self) -> None:
        self.win32con = importlib.import_module("win32con")
        self.win32gui = importlib.import_module("win32gui")

    def _find_optional(self, title: str) -> int | None:
        matches: list[int] = []

        def visit(handle: int, extra: object) -> None:
            del extra
            if self.win32gui.IsWindowVisible(handle) and title in self.win32gui.GetWindowText(
                handle
            ):
                matches.append(handle)

        self.win32gui.EnumWindows(visit, None)
        return matches[0] if matches else None

    def _find(self, title: str) -> int:
        handle = self._find_optional(title)
        if handle is None:
            raise LookupError(f"window not found: {title}")
        return handle

    def query(self, title: str) -> dict[str, Any]:
        handle = self._find_optional(title)
        if handle is None:
            return {"exists": False, "foreground": False, "title": "", "handle": None}
        return {
            "exists": True,
            "foreground": handle == self.win32gui.GetForegroundWindow(),
            "title": self.win32gui.GetWindowText(handle),
            "handle": handle,
        }

    def activate(self, title: str) -> None:
        handle = self._find(title)
        self.win32gui.ShowWindow(handle, self.win32con.SW_RESTORE)
        self.win32gui.SetForegroundWindow(handle)

    def minimize(self, title: str) -> None:
        self.win32gui.ShowWindow(self._find(title), self.win32con.SW_MINIMIZE)

    def restore(self, title: str) -> None:
        self.win32gui.ShowWindow(self._find(title), self.win32con.SW_RESTORE)

    def move_resize(self, title: str, geometry: tuple[int, int, int, int]) -> None:
        x, y, width, height = geometry
        self.win32gui.SetWindowPos(
            self._find(title), None, x, y, width, height, self.win32con.SWP_NOZORDER
        )

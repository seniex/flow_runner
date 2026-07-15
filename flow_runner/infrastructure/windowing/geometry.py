import asyncio
import importlib
from collections.abc import Callable
from typing import Protocol, cast

from flow_runner.domain.capture_targets import parse_window_capture_target

Point = tuple[int, int]
WindowVisitor = Callable[[int, object], None]


class WindowOriginProvider(Protocol):
    async def origin(self, target: str) -> Point: ...


class WindowGeometryBackend(Protocol):
    def EnumWindows(self, visit: WindowVisitor, extra: object) -> None: ...  # noqa: N802

    def IsWindowVisible(self, handle: int) -> bool: ...  # noqa: N802

    def GetWindowText(self, handle: int) -> str: ...  # noqa: N802

    def GetWindowRect(self, handle: int) -> tuple[int, int, int, int]: ...  # noqa: N802


class Win32WindowGeometry:
    def __init__(self, backend: WindowGeometryBackend | None = None) -> None:
        self.backend = backend or cast(
            WindowGeometryBackend,
            importlib.import_module("win32gui"),
        )

    async def origin(self, target: str) -> Point:
        _mode, title = parse_window_capture_target(target)
        return await asyncio.to_thread(self._origin_for_title, title)

    def _origin_for_title(self, title: str) -> Point:
        matches: list[int] = []

        def visit(handle: int, extra: object) -> None:
            del extra
            if self.backend.IsWindowVisible(handle) and title in self.backend.GetWindowText(handle):
                matches.append(handle)

        self.backend.EnumWindows(visit, None)
        if not matches:
            raise LookupError(f"找不到目标窗口：{title}")
        left, top, right, bottom = self.backend.GetWindowRect(matches[0])
        if right <= left or bottom <= top:
            raise ValueError(f"目标窗口边界无效：{(left, top, right, bottom)}")
        return int(left), int(top)

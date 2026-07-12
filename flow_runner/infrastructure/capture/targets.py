import asyncio
import importlib
from collections.abc import Callable
from typing import Protocol

from PIL import Image as PillowImage
from PIL import ImageGrab
from PIL.Image import Image

from flow_runner.domain.errors import ConditionError
from flow_runner.infrastructure.capture.base import CaptureAdapter, CapturedFrame


class WindowBounds(Protocol):
    def bounds(self, title: str) -> tuple[int, int, int, int]: ...


class WindowCapture:
    def __init__(
        self,
        *,
        bounds: WindowBounds | None = None,
        grabber: Callable[[tuple[int, int, int, int]], Image] | None = None,
    ) -> None:
        self.bounds = bounds or _PyWin32WindowBounds()
        self.grabber = grabber or self._grab_bounds

    async def capture(self, target: str) -> CapturedFrame:
        if not target.startswith("window:"):
            raise ConditionError(f"window capture cannot capture target '{target}'")
        title = target.removeprefix("window:").strip()
        if not title:
            raise ConditionError("window capture target requires a title")
        try:
            bounds = await asyncio.to_thread(self.bounds.bounds, title)
            left, top, right, bottom = bounds
            if right <= left or bottom <= top:
                raise ValueError(f"window has invalid bounds: {bounds}")
            image = await asyncio.to_thread(self.grabber, bounds)
            return CapturedFrame(image=image, origin=(left, top))
        except Exception as error:
            raise ConditionError(f"window capture failed for '{title}': {error}") from error

    @staticmethod
    def _grab_bounds(bounds: tuple[int, int, int, int]) -> Image:
        try:
            return _bitblt_bounds(bounds)
        except Exception:
            return ImageGrab.grab(bbox=bounds, all_screens=True)


class TargetCapture:
    def __init__(self, desktop: CaptureAdapter, window: CaptureAdapter) -> None:
        self.desktop = desktop
        self.window = window

    async def capture(self, target: str) -> Image | CapturedFrame:
        if target == "desktop":
            return await self.desktop.capture(target)
        if target.startswith("window:"):
            return await self.window.capture(target)
        raise ConditionError(f"unsupported capture target '{target}'")


class _PyWin32WindowBounds:
    def __init__(self) -> None:
        self.win32gui = importlib.import_module("win32gui")

    def bounds(self, title: str) -> tuple[int, int, int, int]:
        matches: list[int] = []

        def visit(handle: int, extra: object) -> None:
            del extra
            if self.win32gui.IsWindowVisible(handle) and title in self.win32gui.GetWindowText(
                handle
            ):
                matches.append(handle)

        self.win32gui.EnumWindows(visit, None)
        if not matches:
            raise LookupError(f"window not found: {title}")
        return tuple(self.win32gui.GetWindowRect(matches[0]))


def _bitblt_bounds(bounds: tuple[int, int, int, int]) -> Image:
    win32con = importlib.import_module("win32con")
    win32gui = importlib.import_module("win32gui")
    win32ui = importlib.import_module("win32ui")
    left, top, right, bottom = bounds
    width = right - left
    height = bottom - top
    desktop = win32gui.GetDesktopWindow()
    desktop_dc = win32gui.GetWindowDC(desktop)
    source_dc = win32ui.CreateDCFromHandle(desktop_dc)
    memory_dc = source_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    try:
        bitmap.CreateCompatibleBitmap(source_dc, width, height)
        memory_dc.SelectObject(bitmap)
        memory_dc.BitBlt(
            (0, 0),
            (width, height),
            source_dc,
            (left, top),
            win32con.SRCCOPY,
        )
        info = bitmap.GetInfo()
        raw = bitmap.GetBitmapBits(True)
        return PillowImage.frombuffer(
            "RGB",
            (int(info["bmWidth"]), int(info["bmHeight"])),
            raw,
            "raw",
            "BGRX",
            0,
            1,
        )
    finally:
        memory_dc.DeleteDC()
        source_dc.DeleteDC()
        win32gui.ReleaseDC(desktop, desktop_dc)
        win32gui.DeleteObject(bitmap.GetHandle())

import asyncio
import importlib
from collections.abc import Callable
from dataclasses import replace
from typing import Protocol

from PIL import Image as PillowImage
from PIL import ImageGrab
from PIL.Image import Image

from flow_runner.domain.capture_targets import (
    WindowCaptureMode,
    canonical_capture_target,
    parse_window_capture_target,
)
from flow_runner.domain.errors import ConditionError
from flow_runner.infrastructure.capture.base import CaptureAdapter, CapturedFrame

__all__ = [
    "TargetCapture",
    "WindowCapture",
    "WindowCaptureMode",
    "canonical_capture_target",
]


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
        _mode, title = parse_window_capture_target(target)
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
    def __init__(
        self,
        desktop: CaptureAdapter,
        window: CaptureAdapter,
        *,
        background_window: CaptureAdapter | None = None,
        default_window_mode: WindowCaptureMode = WindowCaptureMode.FOREGROUND,
        fallback_to_foreground: bool = True,
    ) -> None:
        self.desktop = desktop
        self.window = window
        self.background_window = background_window
        self.default_window_mode = WindowCaptureMode(default_window_mode)
        self.fallback_to_foreground = fallback_to_foreground

    async def capture(self, target: str) -> Image | CapturedFrame:
        if target == "desktop":
            return await self.desktop.capture(target)
        if target.startswith("window:"):
            mode, title = parse_window_capture_target(target, self.default_window_mode)
            canonical = f"window:{title}"
            if mode is WindowCaptureMode.FOREGROUND:
                frame = await self.window.capture(canonical)
                return _capture_mode_frame(frame, mode)
            if self.background_window is None:
                error: Exception = ConditionError("background window capture is not configured")
            else:
                try:
                    frame = await self.background_window.capture(canonical)
                except Exception as caught:
                    error = caught
                else:
                    return _capture_mode_frame(frame, mode)
            if not self.fallback_to_foreground:
                raise ConditionError(f"background capture failed for '{title}': {error}") from error
            foreground = await self.window.capture(canonical)
            captured = _as_captured_frame(foreground)
            return replace(
                captured,
                metadata={
                    **captured.metadata,
                    "requested_capture_mode": WindowCaptureMode.BACKGROUND.value,
                    "capture_mode": WindowCaptureMode.FOREGROUND.value,
                    "fallback_reason": str(error),
                },
            )
        raise ConditionError(f"unsupported capture target '{target}'")


def _capture_mode_frame(
    frame: Image | CapturedFrame,
    mode: WindowCaptureMode,
) -> CapturedFrame:
    captured = _as_captured_frame(frame)
    return replace(
        captured,
        metadata={**captured.metadata, "capture_mode": mode.value},
    )


def _as_captured_frame(frame: Image | CapturedFrame) -> CapturedFrame:
    return frame if isinstance(frame, CapturedFrame) else CapturedFrame(frame)


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

from __future__ import annotations

import asyncio
import importlib
from typing import Any, Protocol

import numpy as np
from PIL import Image as PillowImage
from PIL.Image import Image

from flow_runner.domain.capture_targets import parse_window_capture_target
from flow_runner.domain.errors import ConditionError
from flow_runner.infrastructure.capture.base import CapturedFrame


class WindowLocator(Protocol):
    def locate(self, title: str) -> tuple[int, tuple[int, int, int, int]]: ...


class GraphicsFrameSource(Protocol):
    async def capture(self, handle: int, timeout_seconds: float) -> Image: ...


class WindowsGraphicsCapture:
    def __init__(
        self,
        *,
        locator: WindowLocator | None = None,
        source: GraphicsFrameSource | None = None,
        timeout_seconds: float = 3.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("graphics capture timeout must be positive")
        self.locator = locator or _Win32WindowLocator()
        self.source = source or WindowsCaptureFrameSource()
        self.timeout_seconds = timeout_seconds

    async def capture(self, target: str) -> CapturedFrame:
        _mode, title = parse_window_capture_target(target)
        try:
            handle, bounds = await asyncio.to_thread(self.locator.locate, title)
            image = await self.source.capture(handle, self.timeout_seconds)
        except Exception as error:
            raise ConditionError(
                f"Windows Graphics Capture failed for '{title}': {error}"
            ) from error
        left, top, _right, _bottom = bounds
        return CapturedFrame(
            image=image,
            origin=(left, top),
            metadata={
                "capture_backend": "windows_graphics_capture",
                "window_handle": handle,
                "window_bounds": bounds,
            },
        )


class _Win32WindowLocator:
    def __init__(self) -> None:
        self.win32gui = importlib.import_module("win32gui")

    def locate(self, title: str) -> tuple[int, tuple[int, int, int, int]]:
        handles: list[int] = []

        def visit(handle: int, extra: object) -> None:
            del extra
            if self.win32gui.IsWindowVisible(handle) and title in self.win32gui.GetWindowText(
                handle
            ):
                handles.append(handle)

        self.win32gui.EnumWindows(visit, None)
        if not handles:
            raise LookupError(f"window not found: {title}")
        handle = handles[0]
        return handle, tuple(self.win32gui.GetWindowRect(handle))


class WindowsCaptureFrameSource:
    def __init__(self, capture_type: Any | None = None) -> None:
        self.capture_type = capture_type

    async def capture(self, handle: int, timeout_seconds: float) -> Image:
        capture_type = self.capture_type
        if capture_type is None:
            capture_type = importlib.import_module("windows_capture").WindowsCapture
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Image] = loop.create_future()
        capture = capture_type(
            cursor_capture=False,
            draw_border=None,
            window_hwnd=handle,
        )

        def on_frame_arrived(frame: Any, control: Any) -> None:
            try:
                buffer = np.asarray(frame.frame_buffer)
                rgb = buffer[:, :, :3][:, :, ::-1].copy()
                image = PillowImage.fromarray(rgb, mode="RGB")
            except Exception as error:
                loop.call_soon_threadsafe(_set_future_exception, future, error)
            else:
                loop.call_soon_threadsafe(_set_future_result, future, image)
            finally:
                control.stop()

        def on_closed() -> None:
            loop.call_soon_threadsafe(
                _set_future_exception,
                future,
                RuntimeError("capture session closed before a frame arrived"),
            )

        capture.event(on_frame_arrived)
        capture.event(on_closed)

        control = capture.start_free_threaded()
        try:
            return await asyncio.wait_for(future, timeout_seconds)
        finally:
            control.stop()
            try:
                await asyncio.wait_for(asyncio.to_thread(control.wait), timeout=2.0)
            except TimeoutError:
                pass


def _set_future_result(future: asyncio.Future[Image], image: Image) -> None:
    if not future.done():
        future.set_result(image)


def _set_future_exception(future: asyncio.Future[Image], error: Exception) -> None:
    if not future.done():
        future.set_exception(error)

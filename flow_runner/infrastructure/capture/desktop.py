import asyncio
import ctypes
import sys
from collections.abc import Callable

from PIL import ImageGrab
from PIL.Image import Image

from flow_runner.domain.errors import ConditionError
from flow_runner.infrastructure.capture.base import CapturedFrame


class DesktopCapture:
    def __init__(
        self,
        grabber: Callable[[], Image] | None = None,
        *,
        origin_provider: Callable[[], tuple[int, int]] | None = None,
    ) -> None:
        self._grabber = grabber or self._grab_all_screens
        self._origin_provider = origin_provider or self._virtual_screen_origin

    async def capture(self, target: str) -> CapturedFrame:
        if target != "desktop":
            raise ConditionError(f"desktop capture cannot capture target '{target}'")
        try:
            image, origin = await asyncio.gather(
                asyncio.to_thread(self._grabber),
                asyncio.to_thread(self._origin_provider),
            )
            return CapturedFrame(image=image, origin=origin)
        except Exception as error:
            raise ConditionError(f"desktop capture failed: {error}") from error

    @staticmethod
    def _grab_all_screens() -> Image:
        return ImageGrab.grab(all_screens=True)

    @staticmethod
    def _virtual_screen_origin() -> tuple[int, int]:
        if sys.platform != "win32":
            return (0, 0)
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        return (
            int(user32.GetSystemMetrics(76)),
            int(user32.GetSystemMetrics(77)),
        )

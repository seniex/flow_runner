import asyncio
from collections.abc import Callable

from PIL import ImageGrab
from PIL.Image import Image

from flow_runner.domain.errors import ConditionError


class DesktopCapture:
    def __init__(self, grabber: Callable[[], Image] | None = None) -> None:
        self._grabber = grabber or self._grab_all_screens

    async def capture(self, target: str) -> Image:
        if target != "desktop":
            raise ConditionError(f"desktop capture cannot capture target '{target}'")
        try:
            return await asyncio.to_thread(self._grabber)
        except Exception as error:
            raise ConditionError(f"desktop capture failed: {error}") from error

    @staticmethod
    def _grab_all_screens() -> Image:
        return ImageGrab.grab(all_screens=True)

from typing import Protocol

from PIL.Image import Image


class CaptureAdapter(Protocol):
    async def capture(self, target: str) -> Image: ...

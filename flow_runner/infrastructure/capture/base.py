from dataclasses import dataclass
from typing import Protocol

from PIL.Image import Image


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    image: Image
    origin: tuple[int, int] = (0, 0)


class CaptureAdapter(Protocol):
    async def capture(self, target: str) -> Image | CapturedFrame: ...

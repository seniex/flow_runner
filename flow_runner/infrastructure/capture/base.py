from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from PIL.Image import Image


@dataclass(frozen=True, slots=True)
class CapturedFrame:
    image: Image
    origin: tuple[int, int] = (0, 0)
    metadata: Mapping[str, Any] = field(default_factory=dict)


class CaptureAdapter(Protocol):
    async def capture(self, target: str) -> Image | CapturedFrame: ...

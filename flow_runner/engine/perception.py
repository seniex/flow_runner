from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from time import monotonic
from typing import Any, Protocol
from uuid import uuid4

from PIL.Image import Image

from flow_runner.infrastructure.capture.base import CaptureAdapter

Region = tuple[int, int, int, int]


class OcrProvider(Protocol):
    name: str

    async def recognize(
        self,
        image: Image,
        *,
        language: str,
        preprocessing: str,
    ) -> Any: ...


@dataclass(frozen=True, slots=True)
class PerceptionSnapshot:
    target: str
    frame_id: str
    scene_generation: int
    captured_at: float
    image: Image

    @property
    def dimensions(self) -> tuple[int, int]:
        return self.image.size


class PerceptionService:
    def __init__(
        self,
        capture: CaptureAdapter,
        *,
        coalesce_window_ms: int = 0,
        cache_limit: int = 128,
        frame_cache_limit: int = 4,
    ) -> None:
        if coalesce_window_ms < 0:
            raise ValueError("coalesce_window_ms cannot be negative")
        if cache_limit <= 0:
            raise ValueError("cache_limit must be positive")
        if frame_cache_limit <= 0:
            raise ValueError("frame_cache_limit must be positive")
        self.capture = capture
        self.coalesce_window_seconds = coalesce_window_ms / 1000
        self.cache_limit = cache_limit
        self.frame_cache_limit = frame_cache_limit
        self._generations: dict[str, int] = {}
        self._latest: dict[str, PerceptionSnapshot] = {}
        self._inflight: dict[str, asyncio.Task[PerceptionSnapshot]] = {}
        self._frame_cache: OrderedDict[str, PerceptionSnapshot] = OrderedDict()
        self._ocr_cache: OrderedDict[tuple[Any, ...], Any] = OrderedDict()

    async def snapshot(self, target: str) -> PerceptionSnapshot:
        generation = self.current_generation(target)
        latest = self._latest.get(target)
        if (
            latest is not None
            and self.coalesce_window_seconds > 0
            and latest.scene_generation == generation
            and monotonic() - latest.captured_at <= self.coalesce_window_seconds
        ):
            return latest

        inflight = self._inflight.get(target)
        if inflight is None:
            inflight = asyncio.create_task(self._capture(target, generation))
            self._inflight[target] = inflight
        try:
            return await inflight
        finally:
            if self._inflight.get(target) is inflight:
                self._inflight.pop(target, None)

    async def _capture(self, target: str, generation: int) -> PerceptionSnapshot:
        image = await self.capture.capture(target)
        snapshot = PerceptionSnapshot(
            target=target,
            frame_id=str(uuid4()),
            scene_generation=generation,
            captured_at=monotonic(),
            image=image,
        )
        if self.current_generation(target) == generation:
            self._latest[target] = snapshot
        self._frame_cache[snapshot.frame_id] = snapshot
        while len(self._frame_cache) > self.frame_cache_limit:
            self._frame_cache.popitem(last=False)
        return snapshot

    async def ocr(
        self,
        snapshot: PerceptionSnapshot,
        *,
        region: Region | None,
        provider: OcrProvider,
        language: str = "",
        preprocessing: str = "",
    ) -> Any:
        key = (
            snapshot.frame_id,
            region,
            provider.name,
            language,
            preprocessing,
        )
        if key in self._ocr_cache:
            self._ocr_cache.move_to_end(key)
            return self._ocr_cache[key]

        image = self.crop_image(snapshot.image, region) if region else snapshot.image
        result = await provider.recognize(
            image,
            language=language,
            preprocessing=preprocessing,
        )
        self._ocr_cache[key] = result
        self._ocr_cache.move_to_end(key)
        while len(self._ocr_cache) > self.cache_limit:
            self._ocr_cache.popitem(last=False)
        return result

    def current_generation(self, target: str) -> int:
        return self._generations.get(target, 0)

    def snapshot_by_frame(self, frame_id: str) -> PerceptionSnapshot | None:
        return self._frame_cache.get(frame_id)

    def mark_scene_changed(self, target: str) -> int:
        generation = self.current_generation(target) + 1
        self._generations[target] = generation
        self._latest.pop(target, None)
        self._ocr_cache.clear()
        return generation

    @staticmethod
    def crop_image(image: Image, region: Region) -> Image:
        left, top, right, bottom = region
        width, height = image.size
        if (
            left < 0
            or top < 0
            or right > width
            or bottom > height
            or right <= left
            or bottom <= top
        ):
            raise ValueError(f"region {region} is outside image bounds {(0, 0, width, height)}")
        return image.crop(region)

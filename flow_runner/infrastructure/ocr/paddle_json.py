from __future__ import annotations

from typing import Any, Protocol

from PIL.Image import Image

from flow_runner.domain.errors import ConditionError
from flow_runner.infrastructure.ocr.base import OcrItem, OcrObservation


class PaddleJsonClient(Protocol):
    async def recognize(self, image: Image) -> list[dict[str, Any]]: ...


class PaddleJsonOcr:
    name = "paddle-json"

    def __init__(self, client: PaddleJsonClient) -> None:
        self.client = client

    async def recognize(
        self,
        image: Image,
        *,
        language: str,
        preprocessing: str,
    ) -> OcrObservation:
        del language, preprocessing
        try:
            rows = await self.client.recognize(image)
            items = [_normalize_row(row) for row in rows]
        except Exception as error:
            raise ConditionError(f"PaddleOCR-json failed: {error}") from error
        return OcrObservation(text=" ".join(item.text for item in items), items=items)


def _normalize_row(row: dict[str, Any]) -> OcrItem:
    points = row["box"]
    xs = [int(point[0]) for point in points]
    ys = [int(point[1]) for point in points]
    return OcrItem(
        text=str(row["text"]),
        bounds=(min(xs), min(ys), max(xs), max(ys)),
        confidence=float(row["score"]),
    )

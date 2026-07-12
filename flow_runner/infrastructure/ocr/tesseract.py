from __future__ import annotations

import asyncio
import importlib
from collections.abc import Callable
from typing import Any, cast

from PIL.Image import Image

from flow_runner.domain.errors import ConditionError
from flow_runner.infrastructure.ocr.base import OcrItem, OcrObservation

ImageToData = Callable[..., dict[str, list[Any]]]


class TesseractOcr:
    name = "tesseract"

    def __init__(self, image_to_data: ImageToData | None = None) -> None:
        self._image_to_data = image_to_data

    async def recognize(
        self,
        image: Image,
        *,
        language: str,
        preprocessing: str,
    ) -> OcrObservation:
        del preprocessing
        try:
            data = await asyncio.to_thread(
                self._recognize_data,
                image,
                language,
            )
        except Exception as error:
            raise ConditionError(f"Tesseract OCR failed: {error}") from error
        return _normalize_data(data)

    def _recognize_data(self, image: Image, language: str) -> dict[str, list[Any]]:
        if self._image_to_data is not None:
            return self._image_to_data(image, lang=language, config="--psm 6 --oem 3")
        try:
            pytesseract = importlib.import_module("pytesseract")
        except ImportError as error:
            raise ConditionError("pytesseract is not installed") from error
        return cast(
            dict[str, list[Any]],
            pytesseract.image_to_data(
                image,
                lang=language,
                config="--psm 6 --oem 3",
                output_type=pytesseract.Output.DICT,
            ),
        )


def _normalize_data(data: dict[str, list[Any]]) -> OcrObservation:
    items: list[OcrItem] = []
    for index, raw_text in enumerate(data.get("text", [])):
        text = str(raw_text).strip()
        if not text:
            continue
        confidence = float(data["conf"][index])
        if confidence < 0:
            continue
        left = int(data["left"][index])
        top = int(data["top"][index])
        right = left + int(data["width"][index])
        bottom = top + int(data["height"][index])
        items.append(
            OcrItem(
                text=text,
                bounds=(left, top, right, bottom),
                confidence=confidence / 100,
            )
        )
    return OcrObservation(text=" ".join(item.text for item in items), items=items)

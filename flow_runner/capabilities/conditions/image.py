from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from flow_runner.domain.enums import ConditionOutcome
from flow_runner.domain.errors import ConditionError
from flow_runner.domain.results import ConditionResult
from flow_runner.engine.perception import PerceptionService, Region


class ImageConditionConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    target: str = "desktop"
    region: Region | None = None
    template_path: Path
    threshold: float = Field(default=0.8, ge=0, le=1)


class ImageCondition:
    name = "vision.image"
    config_model = ImageConditionConfig

    def __init__(self, perception: PerceptionService) -> None:
        self.perception = perception

    async def evaluate(
        self,
        config: ImageConditionConfig,
        context: Any,
    ) -> ConditionResult:
        del context
        if not config.template_path.is_file():
            raise ConditionError(f"template file does not exist: {config.template_path}")
        snapshot = await self.perception.snapshot(config.target)
        image = (
            self.perception.crop_image(snapshot.image, config.region)
            if config.region
            else snapshot.image
        )
        matched, score, local_bounds = await asyncio.to_thread(
            _match_template,
            image,
            config.template_path,
            config.threshold,
        )
        bounds = (
            _offset_bounds(local_bounds, config.region)
            if matched and local_bounds is not None
            else None
        )
        return ConditionResult(
            node_id=self.name,
            outcome=(ConditionOutcome.MATCH if matched else ConditionOutcome.NO_MATCH),
            bounds=bounds,
            position=_center(bounds) if bounds else None,
            confidence=score,
            target=config.target,
            frame_id=snapshot.frame_id,
            scene_generation=snapshot.scene_generation,
            provider_data={
                "frame_id": snapshot.frame_id,
                "template_path": str(config.template_path),
            },
        )

    def required_resources(self, config: ImageConditionConfig) -> frozenset[str]:
        return frozenset({f"observe:{config.target}"})


def _match_template(
    image: Any,
    template_path: Path,
    threshold: float,
) -> tuple[bool, float, Region | None]:
    template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
    if template is None:
        raise ConditionError(f"cannot read template: {template_path}")
    screen = cv2.cvtColor(np.asarray(image), cv2.COLOR_RGB2BGR)
    template_height, template_width = template.shape[:2]
    screen_height, screen_width = screen.shape[:2]
    if template_width > screen_width or template_height > screen_height:
        raise ConditionError("template is larger than the detection region")
    matrix = cv2.matchTemplate(screen, template, cv2.TM_SQDIFF_NORMED)
    minimum, _, location, _ = cv2.minMaxLoc(matrix)
    score = 1.0 - float(minimum)
    if score < threshold:
        return False, score, None
    left, top = location
    return True, score, (left, top, left + template_width, top + template_height)


def _offset_bounds(bounds: Region, region: Region | None) -> Region:
    if region is None:
        return bounds
    left, top, right, bottom = bounds
    return left + region[0], top + region[1], right + region[0], bottom + region[1]


def _center(bounds: Region) -> tuple[int, int]:
    left, top, right, bottom = bounds
    return (left + right) // 2, (top + bottom) // 2

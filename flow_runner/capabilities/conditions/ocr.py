from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from flow_runner.domain.enums import ConditionOutcome
from flow_runner.domain.results import ConditionResult
from flow_runner.engine.perception import OcrProvider, PerceptionService, Region
from flow_runner.infrastructure.ocr.base import OcrItem, OcrObservation


class OcrConditionConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    target: str = "desktop"
    region: Region | None = None
    keywords: str = Field(min_length=1)
    language: str = "chi_sim"
    preprocessing: str = ""


class OcrCondition:
    name = "vision.ocr"
    config_model = OcrConditionConfig

    def __init__(self, perception: PerceptionService, engine: OcrProvider) -> None:
        self.perception = perception
        self.engine = engine

    async def evaluate(
        self,
        config: OcrConditionConfig,
        context: Any,
    ) -> ConditionResult:
        del context
        snapshot = await self.perception.snapshot(config.target)
        observation = await self.perception.ocr(
            snapshot,
            region=config.region,
            provider=self.engine,
            language=config.language,
            preprocessing=config.preprocessing,
        )
        if not isinstance(observation, OcrObservation):
            observation = OcrObservation.model_validate(observation)
        matched_item = _first_matching_item(observation, config.keywords)
        if matched_item is None:
            return ConditionResult(
                node_id=self.name,
                outcome=ConditionOutcome.NO_MATCH,
                text=observation.text,
                target=config.target,
                frame_id=snapshot.frame_id,
                scene_generation=snapshot.scene_generation,
            )
        bounds = _offset_bounds(matched_item.bounds, config.region)
        position = _center(bounds) if bounds else None
        return ConditionResult(
            node_id=self.name,
            outcome=ConditionOutcome.MATCH,
            text=matched_item.text,
            bounds=bounds,
            position=position,
            confidence=matched_item.confidence,
            target=config.target,
            frame_id=snapshot.frame_id,
            scene_generation=snapshot.scene_generation,
            provider_data={"frame_id": snapshot.frame_id},
        )

    def required_resources(self, config: OcrConditionConfig) -> frozenset[str]:
        return frozenset({f"observe:{config.target}"})


def match_keywords(text: str, expression: str) -> bool:
    compact = text.replace(" ", "")
    for group in expression.split("|"):
        keywords = [part.strip() for part in group.split(",") if part.strip()]
        if keywords and all(keyword in text or keyword in compact for keyword in keywords):
            return True
    return False


def _first_matching_item(
    observation: OcrObservation,
    expression: str,
) -> OcrItem | None:
    for item in observation.items:
        if match_keywords(item.text, expression):
            return item
    if match_keywords(observation.text, expression):
        return OcrItem(text=observation.text)
    return None


def _offset_bounds(bounds: Region | None, region: Region | None) -> Region | None:
    if bounds is None or region is None:
        return bounds
    left, top, right, bottom = bounds
    return left + region[0], top + region[1], right + region[0], bottom + region[1]


def _center(bounds: Region) -> tuple[int, int]:
    left, top, right, bottom = bounds
    return (left + right) // 2, (top + bottom) // 2

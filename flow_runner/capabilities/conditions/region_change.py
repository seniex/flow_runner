from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from flow_runner.domain.enums import ConditionOutcome
from flow_runner.domain.results import ConditionResult
from flow_runner.engine.perception import PerceptionService, Region


class RegionChangeConditionConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    target: str = "desktop"
    region: Region
    threshold: float = Field(default=0.1, ge=0, le=1)
    channel_tolerance: int = Field(default=10, ge=0, le=255)


class RegionChangeCondition:
    name = "vision.region_change"
    config_model = RegionChangeConditionConfig

    def __init__(self, perception: PerceptionService) -> None:
        self.perception = perception
        self._previous: dict[tuple[str, Region], np.ndarray[Any, Any]] = {}

    async def evaluate(self, config: RegionChangeConditionConfig, context: Any) -> ConditionResult:
        del context
        snapshot = await self.perception.snapshot(config.target)
        image = self.perception.crop_image(snapshot.image, config.region).convert("RGB")
        current = np.asarray(image, dtype=np.int16)
        key = (config.target, config.region)
        previous = self._previous.get(key)
        self._previous[key] = current
        ratio = (
            0.0
            if previous is None
            else float(
                np.mean(np.any(np.abs(current - previous) > config.channel_tolerance, axis=2))
            )
        )
        return ConditionResult(
            node_id=self.name,
            outcome=ConditionOutcome.MATCH
            if ratio >= config.threshold
            else ConditionOutcome.NO_MATCH,
            confidence=ratio,
            target=config.target,
            frame_id=snapshot.frame_id,
            scene_generation=snapshot.scene_generation,
            provider_data={"frame_id": snapshot.frame_id},
        )

    def required_resources(self, config: RegionChangeConditionConfig) -> frozenset[str]:
        return frozenset({f"observe:{config.target}"})

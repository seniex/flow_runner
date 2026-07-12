from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from flow_runner.domain.enums import ConditionOutcome
from flow_runner.domain.results import ConditionResult
from flow_runner.engine.perception import PerceptionService


class PixelConditionConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    target: str = "desktop"
    position: tuple[int, int]
    color: tuple[int, int, int]
    tolerance: int = Field(default=0, ge=0, le=255)


class PixelCondition:
    name = "vision.pixel"
    config_model = PixelConditionConfig

    def __init__(self, perception: PerceptionService) -> None:
        self.perception = perception

    async def evaluate(self, config: PixelConditionConfig, context: Any) -> ConditionResult:
        del context
        snapshot = await self.perception.snapshot(config.target)
        raw = snapshot.image.convert("RGB").getpixel(config.position)
        if not isinstance(raw, tuple) or len(raw) < 3:
            raise ValueError("RGB pixel lookup did not return three channels")
        actual = (int(raw[0]), int(raw[1]), int(raw[2]))
        matched = all(
            abs(int(a) - e) <= config.tolerance for a, e in zip(actual, config.color, strict=True)
        )
        return ConditionResult(
            node_id=self.name,
            outcome=ConditionOutcome.MATCH if matched else ConditionOutcome.NO_MATCH,
            target=config.target,
            frame_id=snapshot.frame_id,
            scene_generation=snapshot.scene_generation,
            provider_data={"actual": actual, "frame_id": snapshot.frame_id},
        )

    def required_resources(self, config: PixelConditionConfig) -> frozenset[str]:
        return frozenset({f"observe:{config.target}"})

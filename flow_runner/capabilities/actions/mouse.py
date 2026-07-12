from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from flow_runner.domain.enums import StepOutcome
from flow_runner.domain.results import ActionResult
from flow_runner.infrastructure.input.mouse import MouseDevice


class MouseActionConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    operation: Literal["click", "move", "scroll"]
    position: tuple[int, int]
    button: Literal["left", "right", "middle"] = "left"
    clicks: int = Field(default=1, gt=0)
    interval: float = Field(default=0.0, ge=0)
    duration: float = Field(default=0.0, ge=0)
    scroll_units: int = 1


class MouseAction:
    name = "input.mouse"
    config_model = MouseActionConfig
    binds_to_scene = True

    def __init__(self, device: MouseDevice) -> None:
        self.device = device

    async def execute(self, config: MouseActionConfig, context: Any) -> ActionResult:
        del context
        if config.operation == "click":
            await self.device.click(
                position=config.position,
                button=config.button,
                clicks=config.clicks,
                interval=config.interval,
            )
        elif config.operation == "move":
            await self.device.move(position=config.position, duration=config.duration)
        else:
            await self.device.scroll(position=config.position, units=config.scroll_units)
        return ActionResult(outcome=StepOutcome.SUCCESS)

    def required_resources(self, config: MouseActionConfig) -> frozenset[str]:
        del config
        return frozenset({"mouse"})

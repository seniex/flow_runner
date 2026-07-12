import random
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from flow_runner.domain.enums import StepOutcome
from flow_runner.domain.results import ActionResult
from flow_runner.infrastructure.input.mouse import MouseDevice


class MouseActionConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    operation: Literal[
        "click",
        "move",
        "scroll",
        "button_down",
        "button_up",
        "drag",
    ]
    position: tuple[int, int]
    offset: tuple[int, int] = (0, 0)
    button: Literal["left", "right", "middle"] = "left"
    clicks: int = Field(default=1, gt=0)
    interval: float = Field(default=0.0, ge=0)
    duration: float = Field(default=0.0, ge=0)
    scroll_units: int = 1
    jitter_pixels: int = Field(default=0, ge=0)


class MouseAction:
    name = "input.mouse"
    config_model = MouseActionConfig
    binds_to_scene = True

    def __init__(
        self,
        device: MouseDevice,
        *,
        randint: Callable[[int, int], int] = random.randint,
    ) -> None:
        self.device = device
        self.randint = randint

    async def execute(self, config: MouseActionConfig, context: Any) -> ActionResult:
        del context
        position = (
            config.position[0] + config.offset[0],
            config.position[1] + config.offset[1],
        )
        if config.jitter_pixels:
            position = (
                position[0] + self.randint(-config.jitter_pixels, config.jitter_pixels),
                position[1] + self.randint(-config.jitter_pixels, config.jitter_pixels),
            )
        if config.operation == "click":
            await self.device.click(
                position=position,
                button=config.button,
                clicks=config.clicks,
                interval=config.interval,
            )
        elif config.operation == "move":
            await self.device.move(position=position, duration=config.duration)
        elif config.operation == "scroll":
            await self.device.scroll(position=position, units=config.scroll_units)
        elif config.operation == "button_down":
            await self.device.button_down(position=position, button=config.button)
        elif config.operation == "button_up":
            await self.device.button_up(position=position, button=config.button)
        else:
            await self.device.drag(
                position=position,
                button=config.button,
                duration=config.duration,
            )
        return ActionResult(outcome=StepOutcome.SUCCESS)

    def required_resources(self, config: MouseActionConfig) -> frozenset[str]:
        del config
        return frozenset({"mouse"})

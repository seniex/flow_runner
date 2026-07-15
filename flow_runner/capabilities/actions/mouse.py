import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from flow_runner.domain.capture_targets import canonical_capture_target
from flow_runner.domain.enums import StepOutcome
from flow_runner.domain.errors import ActionError
from flow_runner.domain.results import ActionResult
from flow_runner.infrastructure.input.mouse import MouseDevice

WindowOrigin = Callable[[str], Awaitable[tuple[int, int]]]


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
    settle_delay: float = Field(default=0.0, ge=0)
    target: str = "desktop"
    coordinate_space: Literal["screen", "target"] = "screen"

    @model_validator(mode="after")
    def validate_target_coordinate_space(self) -> "MouseActionConfig":
        if self.target != "desktop" and not self.target.startswith("window:"):
            raise ValueError("mouse target must be desktop or window:<title>")
        if self.coordinate_space == "target" and not self.target.startswith("window:"):
            raise ValueError("target coordinates require a window target")
        return self


class MouseAction:
    name = "input.mouse"
    config_model = MouseActionConfig
    binds_to_scene = True

    def __init__(
        self,
        device: MouseDevice,
        *,
        window_origin: WindowOrigin | None = None,
        randint: Callable[[int, int], int] = random.randint,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.device = device
        self.window_origin = window_origin
        self.randint = randint
        self.sleep = sleep

    async def execute(self, config: MouseActionConfig, context: Any) -> ActionResult:
        del context
        position = config.position
        if config.coordinate_space == "target":
            if self.window_origin is None:
                raise ActionError("窗口相对坐标解析器未配置")
            origin = await self.window_origin(config.target)
            position = (position[0] + origin[0], position[1] + origin[1])
        position = (position[0] + config.offset[0], position[1] + config.offset[1])
        if config.jitter_pixels:
            position = (
                position[0] + self.randint(-config.jitter_pixels, config.jitter_pixels),
                position[1] + self.randint(-config.jitter_pixels, config.jitter_pixels),
            )
        if config.operation == "click":
            if config.duration > 0:
                await self.device.move(position=position, duration=config.duration)
            if config.settle_delay > 0:
                await self.sleep(config.settle_delay)
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
        resources = {"mouse"}
        if config.target.startswith("window:"):
            resources.add(canonical_capture_target(config.target))
        return frozenset(resources)

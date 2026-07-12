from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from flow_runner.domain.enums import StepOutcome
from flow_runner.domain.results import ActionResult
from flow_runner.infrastructure.windowing.win32 import WindowController


class WindowActionConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    operation: Literal["activate", "minimize", "restore", "move_resize"]
    title: str
    geometry: tuple[int, int, int, int] | None = None

    @model_validator(mode="after")
    def validate_geometry(self) -> "WindowActionConfig":
        if self.operation == "move_resize" and self.geometry is None:
            raise ValueError("move_resize requires geometry")
        return self


class WindowAction:
    name = "system.window_action"
    config_model = WindowActionConfig

    def __init__(self, controller: WindowController) -> None:
        self.controller = controller

    async def execute(self, config: WindowActionConfig, context: Any) -> ActionResult:
        del context
        if config.operation == "activate":
            await self.controller.activate(config.title)
        elif config.operation == "minimize":
            await self.controller.minimize(config.title)
        elif config.operation == "restore":
            await self.controller.restore(config.title)
        else:
            assert config.geometry is not None
            await self.controller.move_resize(config.title, config.geometry)
        return ActionResult(outcome=StepOutcome.SUCCESS)

    def required_resources(self, config: WindowActionConfig) -> frozenset[str]:
        return frozenset({f"window:{config.title}"})

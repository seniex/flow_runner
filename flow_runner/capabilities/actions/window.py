from typing import Any, Literal

from pydantic import model_validator

from flow_runner.domain.enums import StepOutcome
from flow_runner.domain.results import ActionResult
from flow_runner.domain.window_targets import WindowTarget
from flow_runner.infrastructure.windowing.win32 import WindowController


class WindowActionConfig(WindowTarget):
    operation: Literal["activate", "minimize", "restore", "move_resize"]
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
            provider_data = await self.controller.activate(config)
        elif config.operation == "minimize":
            provider_data = await self.controller.minimize(config)
        elif config.operation == "restore":
            provider_data = await self.controller.restore(config)
        else:
            assert config.geometry is not None
            provider_data = await self.controller.move_resize(config, config.geometry)
        return ActionResult(outcome=StepOutcome.SUCCESS, provider_data=provider_data)

    def required_resources(self, config: WindowActionConfig) -> frozenset[str]:
        return frozenset({config.resource_key})

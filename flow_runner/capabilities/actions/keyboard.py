from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from flow_runner.domain.enums import StepOutcome
from flow_runner.domain.results import ActionResult
from flow_runner.infrastructure.input.keyboard import KeyboardDevice


class KeyboardActionConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    operation: Literal["press", "hotkey", "write"]
    key: str = ""
    keys: list[str] = Field(default_factory=list)
    text: str = ""
    count: int = Field(default=1, gt=0)
    interval: float = Field(default=0.0, ge=0)


class KeyboardAction:
    name = "input.keyboard"
    config_model = KeyboardActionConfig

    def __init__(self, device: KeyboardDevice) -> None:
        self.device = device

    async def execute(self, config: KeyboardActionConfig, context: Any) -> ActionResult:
        del context
        if config.operation == "press":
            await self.device.press(config.key, config.count, config.interval)
        elif config.operation == "hotkey":
            await self.device.hotkey(tuple(config.keys))
        else:
            await self.device.write(config.text, config.interval)
        return ActionResult(outcome=StepOutcome.SUCCESS)

    def required_resources(self, config: KeyboardActionConfig) -> frozenset[str]:
        del config
        return frozenset({"keyboard"})

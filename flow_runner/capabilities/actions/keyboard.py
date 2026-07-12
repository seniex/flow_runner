from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from flow_runner.domain.enums import StepOutcome
from flow_runner.domain.results import ActionResult
from flow_runner.infrastructure.input.keyboard import KeyboardDevice, TextMode


class KeyboardActionConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    operation: Literal["press", "hotkey", "write", "key_down", "key_up"]
    key: str = ""
    keys: list[str] = Field(default_factory=list)
    text: str = ""
    text_mode: TextMode = "keys"
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
        elif config.operation == "write":
            await self.device.write(config.text, config.interval, config.text_mode)
        elif config.operation == "key_down":
            await self.device.key_down(config.key)
        else:
            await self.device.key_up(config.key)
        return ActionResult(outcome=StepOutcome.SUCCESS)

    def required_resources(self, config: KeyboardActionConfig) -> frozenset[str]:
        del config
        return frozenset({"keyboard"})

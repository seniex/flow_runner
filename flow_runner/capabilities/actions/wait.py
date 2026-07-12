from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from flow_runner.domain.enums import StepOutcome
from flow_runner.domain.results import ActionResult


class WaitActionConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    seconds: float = Field(ge=0)


class WaitAction:
    name = "system.wait"
    config_model = WaitActionConfig

    def __init__(self, sleep: Callable[[float], Awaitable[None]]) -> None:
        self.sleep = sleep

    async def execute(self, config: WaitActionConfig, context: Any) -> ActionResult:
        del context
        await self.sleep(config.seconds)
        return ActionResult(outcome=StepOutcome.SUCCESS)

    def required_resources(self, config: WaitActionConfig) -> frozenset[str]:
        del config
        return frozenset()

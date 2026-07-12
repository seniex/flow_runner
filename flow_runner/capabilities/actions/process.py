from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from flow_runner.domain.enums import StepOutcome
from flow_runner.domain.errors import ActionError
from flow_runner.domain.results import ActionResult

ProcessLauncher = Callable[[Path, tuple[str, ...], bool], Awaitable[None]]


class LaunchProcessConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    path: Path
    arguments: list[str] = Field(default_factory=list)
    run_as_admin: bool = False


class LaunchProcessAction:
    name = "system.launch"
    config_model = LaunchProcessConfig

    def __init__(self, launcher: ProcessLauncher) -> None:
        self.launcher = launcher

    async def execute(self, config: LaunchProcessConfig, context: Any) -> ActionResult:
        del context
        path = config.path.resolve()
        if not path.is_file():
            raise ActionError(f"process path does not exist: {path}")
        await self.launcher(path, tuple(config.arguments), config.run_as_admin)
        return ActionResult(outcome=StepOutcome.SUCCESS)

    def required_resources(self, config: LaunchProcessConfig) -> frozenset[str]:
        del config
        return frozenset()

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from flow_runner.domain.enums import StepOutcome
from flow_runner.domain.errors import ActionError
from flow_runner.domain.results import ActionResult

ProcessLauncher = Callable[[Path, tuple[str, ...], bool, Path | None], Awaitable[None]]


class LaunchProcessConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    path: Path
    arguments: list[str] = Field(default_factory=list)
    run_as_admin: bool = False
    working_directory: Path | None = None


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
        working_directory = (
            config.working_directory.resolve() if config.working_directory is not None else None
        )
        if working_directory is not None and not working_directory.is_dir():
            raise ActionError(f"working directory does not exist: {working_directory}")
        await self.launcher(
            path,
            tuple(config.arguments),
            config.run_as_admin,
            working_directory,
        )
        return ActionResult(outcome=StepOutcome.SUCCESS)

    def required_resources(self, config: LaunchProcessConfig) -> frozenset[str]:
        del config
        return frozenset()

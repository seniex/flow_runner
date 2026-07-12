from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from flow_runner.domain.enums import StepOutcome
from flow_runner.domain.errors import ActionError
from flow_runner.domain.results import ActionResult

Playback = Callable[[Path, float, float], Awaitable[None]]


class PlaybackScriptConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    path: Path
    speed: float = Field(default=1.0, gt=0)
    max_gap: float = Field(default=2.0, ge=0)


class PlaybackScriptAction:
    name = "recording.playback"
    config_model = PlaybackScriptConfig

    def __init__(self, playback: Playback) -> None:
        self.playback = playback

    async def execute(self, config: PlaybackScriptConfig, context: Any) -> ActionResult:
        del context
        path = config.path.resolve()
        if not path.is_file():
            raise ActionError(f"recording path does not exist: {path}")
        await self.playback(path, config.speed, config.max_gap)
        return ActionResult(outcome=StepOutcome.SUCCESS)

    def required_resources(self, config: PlaybackScriptConfig) -> frozenset[str]:
        del config
        return frozenset({"mouse", "keyboard"})

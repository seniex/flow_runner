from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, time
from time import monotonic
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

from flow_runner.domain.enums import ConditionOutcome
from flow_runner.domain.results import ConditionResult
from flow_runner.engine.context import StepContext


class TimeConditionConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    mode: Literal["elapsed", "local_range"]
    started_at: float | None = None
    seconds: float | None = None
    start: str | None = None
    end: str | None = None

    @model_validator(mode="after")
    def validate_mode_fields(self) -> TimeConditionConfig:
        if self.mode == "elapsed" and (self.started_at is None or self.seconds is None):
            raise ValueError("elapsed mode requires started_at and seconds")
        if self.mode == "local_range" and (self.start is None or self.end is None):
            raise ValueError("local_range mode requires start and end")
        return self


class TimeCondition:
    name = "time.check"
    config_model = TimeConditionConfig

    def __init__(
        self,
        monotonic_clock: Callable[[], float] = monotonic,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.monotonic_clock = monotonic_clock
        self.now = now

    async def evaluate(self, config: TimeConditionConfig, context: StepContext) -> ConditionResult:
        del context
        if config.mode == "elapsed":
            assert config.started_at is not None and config.seconds is not None
            matched = self.monotonic_clock() - config.started_at >= config.seconds
        else:
            assert config.start is not None and config.end is not None
            matched = _in_time_range(
                self.now().time(), _parse_time(config.start), _parse_time(config.end)
            )
        return ConditionResult(
            node_id=self.name,
            outcome=ConditionOutcome.MATCH if matched else ConditionOutcome.NO_MATCH,
        )

    def required_resources(self, config: TimeConditionConfig) -> frozenset[str]:
        del config
        return frozenset()


def _parse_time(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()


def _in_time_range(current: time, start: time, end: time) -> bool:
    if start <= end:
        return start <= current <= end
    return current >= start or current <= end

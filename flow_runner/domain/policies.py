from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from flow_runner.domain.actions import ActionSpec
from flow_runner.domain.enums import ConditionMode


class ConditionPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    mode: ConditionMode = ConditionMode.ONCE
    interval_seconds: float = Field(default=1.0, ge=0)
    max_attempts: int | None = Field(default=1, gt=0)
    timeout_seconds: float | None = Field(default=None, gt=0)
    before_attempt_actions: list[ActionSpec] = Field(default_factory=list)
    after_no_match_actions: list[ActionSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_mode_limits(self) -> ConditionPolicy:
        if self.mode is ConditionMode.ONCE and self.max_attempts != 1:
            raise ValueError("ONCE condition policy requires max_attempts=1")
        if (
            self.mode is ConditionMode.UNTIL
            and self.max_attempts is None
            and self.timeout_seconds is None
        ):
            raise ValueError("UNTIL condition policy requires a finite attempt or timeout limit")
        return self


class ActionPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_attempts: int = Field(default=1, gt=0)
    retry_interval_seconds: float = Field(default=0.0, ge=0)

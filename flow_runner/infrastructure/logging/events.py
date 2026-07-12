from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from flow_runner.domain.enums import RunnerState, StepOutcome


class RuntimeEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    event_id: UUID = Field(default_factory=uuid4)
    task_id: UUID
    kind: str
    state: RunnerState
    monotonic_timestamp: float
    workflow_id: UUID | None = None
    step_id: UUID | None = None
    outcome: StepOutcome | None = None
    frame_id: str | None = None
    diagnostic_capture_path: str | None = None
    diagnostic_capture_base64: str | None = None
    error_id: UUID | None = None
    details: dict[str, Any] = Field(default_factory=dict)

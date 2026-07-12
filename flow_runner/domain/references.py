from uuid import UUID

from pydantic import BaseModel, ConfigDict


class WorkflowRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    workflow_id: UUID


class StepRef(BaseModel):
    model_config = ConfigDict(frozen=True)

    step_id: UUID


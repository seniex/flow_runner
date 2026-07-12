from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from flow_runner.domain.enums import ConditionOutcome
from flow_runner.domain.results import ConditionResult
from flow_runner.infrastructure.processes.query import ProcessQuery


class ProcessConditionConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str = Field(min_length=1)


class ProcessCondition:
    name = "system.process"
    config_model = ProcessConditionConfig

    def __init__(self, query: ProcessQuery) -> None:
        self.query = query

    async def evaluate(self, config: ProcessConditionConfig, context: Any) -> ConditionResult:
        del context
        matched = self.query.exists(config.name)
        return ConditionResult(
            node_id=self.name,
            outcome=ConditionOutcome.MATCH if matched else ConditionOutcome.NO_MATCH,
        )

    def required_resources(self, config: ProcessConditionConfig) -> frozenset[str]:
        del config
        return frozenset()

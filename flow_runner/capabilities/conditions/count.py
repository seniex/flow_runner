from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from flow_runner.capabilities.conditions.scalar import compare_values
from flow_runner.domain.enums import ConditionOutcome
from flow_runner.domain.results import ConditionResult
from flow_runner.domain.routing import ComparisonOperator
from flow_runner.engine.context import StepContext


class CountConditionConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    counter: Literal["workflow", "step"]
    target_id: UUID
    operator: ComparisonOperator
    expected: int = Field(ge=0)


class CountCondition:
    name = "runtime.count"
    config_model = CountConditionConfig

    async def evaluate(self, config: CountConditionConfig, context: StepContext) -> ConditionResult:
        counts = context.workflow_counts if config.counter == "workflow" else context.step_counts
        actual = counts.get(config.target_id, 0)
        matched = compare_values(actual, config.operator, config.expected)
        return ConditionResult(
            node_id=self.name,
            outcome=ConditionOutcome.MATCH if matched else ConditionOutcome.NO_MATCH,
            provider_data={"actual": actual},
        )

    def required_resources(self, config: CountConditionConfig) -> frozenset[str]:
        del config
        return frozenset()

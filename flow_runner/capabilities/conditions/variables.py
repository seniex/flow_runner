from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from flow_runner.capabilities.conditions.scalar import compare_values
from flow_runner.domain.enums import ConditionOutcome
from flow_runner.domain.errors import ConditionError
from flow_runner.domain.results import ConditionResult
from flow_runner.domain.routing import ComparisonOperator
from flow_runner.engine.context import StepContext


class VariableConditionConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    scope: Literal["task", "workflow", "persistent"]
    name: str = Field(min_length=1)
    operator: ComparisonOperator
    expected: Any


class VariableCondition:
    name = "variables.compare"
    config_model = VariableConditionConfig

    async def evaluate(
        self, config: VariableConditionConfig, context: StepContext
    ) -> ConditionResult:
        values = {
            "task": context.task_variables,
            "workflow": context.workflow_variables,
            "persistent": context.persistent_variables,
        }[config.scope]
        if config.name not in values:
            raise ConditionError(f"missing {config.scope} variable '{config.name}'")
        matched = compare_values(values[config.name], config.operator, config.expected)
        return ConditionResult(
            node_id=self.name,
            outcome=ConditionOutcome.MATCH if matched else ConditionOutcome.NO_MATCH,
            provider_data={"actual": values[config.name]},
        )

    def required_resources(self, config: VariableConditionConfig) -> frozenset[str]:
        del config
        return frozenset()

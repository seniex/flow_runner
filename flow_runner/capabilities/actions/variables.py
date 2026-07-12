from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from flow_runner.domain.enums import StepOutcome
from flow_runner.domain.results import ActionResult
from flow_runner.engine.context import StepContext


class SetVariableConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    scope: Literal["task", "workflow", "persistent"]
    name: str = Field(min_length=1, pattern=r"^[A-Za-z_][\w-]*$")
    value: Any


class SetVariableAction:
    name = "variables.set"
    config_model = SetVariableConfig

    async def execute(
        self,
        config: SetVariableConfig,
        context: StepContext,
    ) -> ActionResult:
        variables = {
            "task": context.task_variables,
            "workflow": context.workflow_variables,
            "persistent": context.persistent_variables,
        }[config.scope]
        variables[config.name] = config.value
        return ActionResult(outcome=StepOutcome.SUCCESS, value=config.value)

    def required_resources(self, config: SetVariableConfig) -> frozenset[str]:
        del config
        return frozenset()

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from flow_runner.domain.enums import ConditionOutcome
from flow_runner.domain.results import ConditionResult
from flow_runner.infrastructure.windowing.win32 import WindowQuery


class WindowConditionConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    title: str = Field(min_length=1)
    require_foreground: bool = False


class WindowCondition:
    name = "system.window"
    config_model = WindowConditionConfig

    def __init__(self, query: WindowQuery) -> None:
        self.query = query

    async def evaluate(self, config: WindowConditionConfig, context: Any) -> ConditionResult:
        del context
        data = self.query.query(config.title)
        matched = bool(data.get("exists")) and (
            not config.require_foreground or bool(data.get("foreground"))
        )
        return ConditionResult(
            node_id=self.name,
            outcome=ConditionOutcome.MATCH if matched else ConditionOutcome.NO_MATCH,
            text=str(data.get("title", "")),
            provider_data=data,
        )

    def required_resources(self, config: WindowConditionConfig) -> frozenset[str]:
        del config
        return frozenset()

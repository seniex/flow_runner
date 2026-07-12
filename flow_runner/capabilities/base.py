from typing import Any, Protocol

from pydantic import BaseModel

from flow_runner.domain.results import ActionResult, ConditionResult


class ConditionCapability(Protocol):
    name: str
    config_model: type[BaseModel]

    async def evaluate(self, config: BaseModel, context: Any) -> ConditionResult: ...

    def required_resources(self, config: BaseModel) -> frozenset[str]: ...


class ActionCapability(Protocol):
    name: str
    config_model: type[BaseModel]

    async def execute(self, config: BaseModel, context: Any) -> ActionResult: ...

    def required_resources(self, config: BaseModel) -> frozenset[str]: ...

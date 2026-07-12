from dataclasses import dataclass
from typing import Literal, TypeVar

from pydantic import BaseModel

from flow_runner.capabilities.base import ActionCapability, ConditionCapability
from flow_runner.domain.errors import ConfigurationError

CapabilityT = TypeVar("CapabilityT")


@dataclass(frozen=True, slots=True)
class CapabilityMetadata:
    name: str
    kind: Literal["condition", "action"]
    config_model: type[BaseModel]


class CapabilityRegistry:
    def __init__(self) -> None:
        self._conditions: dict[str, ConditionCapability] = {}
        self._actions: dict[str, ActionCapability] = {}

    def register_condition(self, capability: ConditionCapability) -> None:
        self._register(capability.name, capability, self._conditions, "condition")

    def register_action(self, capability: ActionCapability) -> None:
        self._register(capability.name, capability, self._actions, "action")

    def condition(self, name: str) -> ConditionCapability:
        try:
            return self._conditions[name]
        except KeyError as error:
            raise ConfigurationError(f"unknown condition capability: {name}") from error

    def action(self, name: str) -> ActionCapability:
        try:
            return self._actions[name]
        except KeyError as error:
            raise ConfigurationError(f"unknown action capability: {name}") from error

    def condition_metadata(self) -> tuple[CapabilityMetadata, ...]:
        return tuple(
            CapabilityMetadata(name, "condition", capability.config_model)
            for name, capability in sorted(self._conditions.items())
        )

    def action_metadata(self) -> tuple[CapabilityMetadata, ...]:
        return tuple(
            CapabilityMetadata(name, "action", capability.config_model)
            for name, capability in sorted(self._actions.items())
        )

    @staticmethod
    def _register(
        name: str,
        capability: CapabilityT,
        target: dict[str, CapabilityT],
        kind: str,
    ) -> None:
        if name in target:
            raise ConfigurationError(f"duplicate {kind} capability: {name}")
        target[name] = capability

from dataclasses import dataclass
from typing import Any, Literal, TypeVar, cast

from pydantic import BaseModel, TypeAdapter

from flow_runner.domain.actions import ActionSpec
from flow_runner.domain.binding_expressions import is_binding_expression
from flow_runner.domain.conditions import ConditionGroup, ConditionNode, LeafCondition
from flow_runner.domain.errors import ConfigurationError
from flow_runner.domain.project import Project

CapabilityT = TypeVar("CapabilityT")


@dataclass(frozen=True, slots=True)
class CapabilityMetadata:
    name: str
    kind: Literal["condition", "action"]
    config_model: type[BaseModel]


class CapabilityRegistry:
    def __init__(self) -> None:
        self._conditions: dict[str, Any] = {}
        self._actions: dict[str, Any] = {}

    def register_condition(self, capability: Any) -> None:
        self._register(capability.name, capability, self._conditions, "condition")

    def register_action(self, capability: Any) -> None:
        self._register(capability.name, capability, self._actions, "action")

    def condition(self, name: str) -> Any:
        try:
            return self._conditions[name]
        except KeyError as error:
            raise ConfigurationError(f"unknown condition capability: {name}") from error

    def action(self, name: str) -> Any:
        try:
            return self._actions[name]
        except KeyError as error:
            raise ConfigurationError(f"unknown action capability: {name}") from error

    def condition_metadata(self) -> tuple[CapabilityMetadata, ...]:
        return tuple(
            CapabilityMetadata(name, "condition", cast(type[BaseModel], capability.config_model))
            for name, capability in sorted(self._conditions.items())
        )

    def action_metadata(self) -> tuple[CapabilityMetadata, ...]:
        return tuple(
            CapabilityMetadata(name, "action", cast(type[BaseModel], capability.config_model))
            for name, capability in sorted(self._actions.items())
        )

    def validate_project(self, project: Project) -> list[str]:
        errors: list[str] = []
        for group_index, group in enumerate(project.groups):
            for workflow_index, workflow in enumerate(group.workflows):
                for step_index, step in enumerate(workflow.steps):
                    prefix = (
                        f"groups[{group_index}].workflows[{workflow_index}]."
                        f"steps[{step_index}]('{step.name}')"
                    )
                    if step.condition is not None:
                        self._validate_condition(
                            step.condition,
                            f"{prefix}.condition",
                            errors,
                        )
                    self._validate_actions(step.actions, f"{prefix}.actions", errors)
                    self._validate_actions(
                        step.condition_policy.before_attempt_actions,
                        f"{prefix}.condition_policy.before_attempt_actions",
                        errors,
                    )
                    self._validate_actions(
                        step.condition_policy.after_no_match_actions,
                        f"{prefix}.condition_policy.after_no_match_actions",
                        errors,
                    )
        return errors

    def validate_project_or_raise(self, project: Project) -> None:
        errors = self.validate_project(project)
        if errors:
            raise ConfigurationError(
                "invalid project capability configuration:\n- " + "\n- ".join(errors)
            )

    def _validate_condition(
        self,
        node: ConditionNode,
        path: str,
        errors: list[str],
    ) -> None:
        if isinstance(node, ConditionGroup):
            for index, child in enumerate(node.children):
                self._validate_condition(child, f"{path}.children[{index}]", errors)
            return
        assert isinstance(node, LeafCondition)
        try:
            provider = self.condition(node.capability)
            provider.config_model.model_validate(node.config)
        except (ConfigurationError, ValueError) as error:
            errors.append(f"{path}('{node.id}', {node.capability}): {error}")

    def _validate_actions(
        self,
        actions: list[ActionSpec],
        path: str,
        errors: list[str],
    ) -> None:
        for index, action in enumerate(actions):
            try:
                provider = self.action(action.capability)
                _validate_action_config(provider.config_model, action.config)
            except (ConfigurationError, ValueError) as error:
                errors.append(f"{path}[{index}]({action.capability}): {error}")

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


def _validate_action_config(model_type: type[BaseModel], config: dict[str, Any]) -> None:
    if not _contains_binding(config):
        model_type.model_validate(config)
        return
    for name, field in model_type.model_fields.items():
        if field.is_required() and name not in config:
            raise ValueError(f"required field '{name}' is missing")
        if name not in config or _contains_binding(config[name]):
            continue
        TypeAdapter(field.rebuild_annotation()).validate_python(config[name])


def _contains_binding(value: Any) -> bool:
    if isinstance(value, str):
        if not value.startswith("$"):
            return False
        if not is_binding_expression(value):
            raise ValueError(f"unsupported binding expression: {value}")
        return True
    if isinstance(value, dict):
        return any(_contains_binding(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return any(_contains_binding(item) for item in value)
    return False

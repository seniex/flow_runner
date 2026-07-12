from typing import Any

from pydantic import BaseModel

from flow_runner.domain.conditions import LeafCondition
from flow_runner.domain.project import AutomationStep


def switch_condition_capability(
    step: AutomationStep,
    capability: str,
    config_model: type[BaseModel],
    *,
    required_config: dict[str, Any] | None = None,
) -> tuple[AutomationStep, dict[str, Any]]:
    condition = step.condition
    if not isinstance(condition, LeafCondition):
        raise ValueError("capability switching requires a leaf condition")
    allowed = set(config_model.model_fields)
    preserved = {key: value for key, value in condition.config.items() if key in allowed}
    discarded = {key: value for key, value in condition.config.items() if key not in allowed}
    preserved.update(required_config or {})
    validated = config_model.model_validate(preserved).model_dump(mode="python")
    replacement = LeafCondition(
        id=condition.id,
        capability=capability,
        config=validated,
    )
    return step.model_copy(update={"condition": replacement}), discarded

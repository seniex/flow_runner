import json
from dataclasses import dataclass

from flow_runner.domain.conditions import ConditionGroup, ConditionNode, LeafCondition
from flow_runner.ui.localization import capability_label, result_field_label


@dataclass(frozen=True, slots=True)
class ResultBindingOption:
    expression: str
    label: str
    field: str


RESULT_FIELDS = {
    "vision.ocr": ("position", "bounds", "text", "confidence"),
    "vision.image": ("position", "bounds", "confidence"),
    "vision.pixel": ("position",),
}


def result_binding_options(
    condition: ConditionNode | None,
) -> tuple[ResultBindingOption, ...]:
    if condition is None:
        return ()
    options: list[ResultBindingOption] = []
    if isinstance(condition, LeafCondition) or condition.operator == "or":
        fields = _primary_fields(condition)
        options.extend(
            ResultBindingOption(
                f"$result.primary.{field}",
                f"当前步骤检测结果 → 主要结果 → {result_field_label(field)}",
                field,
            )
            for field in fields
        )
    if isinstance(condition, ConditionGroup):
        for child in condition.children:
            if not isinstance(child, LeafCondition):
                continue
            for field in RESULT_FIELDS.get(child.capability, ()):
                expression = (
                    f"$result.children[{json.dumps(child.id, ensure_ascii=False)}].{field}"
                )
                label = (
                    f"{capability_label(child.capability)}「{child.id}」→ "
                    f"{result_field_label(field)}"
                )
                options.append(ResultBindingOption(expression, label, field))
    return tuple(options)


def _primary_fields(condition: ConditionNode) -> tuple[str, ...]:
    if isinstance(condition, LeafCondition):
        return RESULT_FIELDS.get(condition.capability, ())
    fields = {
        field
        for child in condition.children
        if isinstance(child, LeafCondition)
        for field in RESULT_FIELDS.get(child.capability, ())
    }
    return tuple(
        field for field in ("position", "bounds", "text", "confidence") if field in fields
    )

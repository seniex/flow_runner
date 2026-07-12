from typing import Any

from flow_runner.domain.binding_expressions import (
    CHILD_PATTERN,
    PRIMARY_PATTERN,
    VARIABLE_PATTERN,
)
from flow_runner.domain.errors import BindingError
from flow_runner.domain.results import ConditionResult
from flow_runner.engine.context import StepContext


def resolve_binding(expression: str, context: StepContext) -> Any:
    primary_match = PRIMARY_PATTERN.fullmatch(expression)
    if primary_match:
        result = _require_result(context)
        primary = result.primary
        if primary is None:
            raise BindingError("result primary is unavailable or ambiguous")
        return _result_field(primary, primary_match.group("field"))

    child_match = CHILD_PATTERN.fullmatch(expression)
    if child_match:
        result = _require_result(context)
        alias = child_match.group("alias")
        try:
            child = result.children[alias]
        except KeyError as error:
            raise BindingError(f"result child '{alias}' does not exist") from error
        return _result_field(child, child_match.group("field"))

    variable_match = VARIABLE_PATTERN.fullmatch(expression)
    if variable_match:
        scope = variable_match.group("scope")
        name = variable_match.group("name")
        variables = {
            "task": context.task_variables,
            "workflow": context.workflow_variables,
            "persistent": context.persistent_variables,
        }[scope]
        try:
            return variables[name]
        except KeyError as error:
            raise BindingError(f"{scope} variable '{name}' does not exist") from error

    raise BindingError(f"unsupported binding expression: {expression}")


def _require_result(context: StepContext) -> ConditionResult:
    if context.result is None:
        raise BindingError("current step has no condition result")
    return context.result


def _result_field(result: ConditionResult, field: str) -> Any:
    return getattr(result, field)

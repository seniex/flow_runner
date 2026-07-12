import pytest

from flow_runner.domain.enums import ConditionOutcome
from flow_runner.domain.errors import BindingError
from flow_runner.domain.results import ConditionResult
from flow_runner.engine.bindings import resolve_binding
from flow_runner.engine.context import StepContext


def test_binding_reads_named_child_and_variable():
    result = ConditionResult.and_group(
        "all",
        [ConditionResult(node_id="ocr_a", outcome=ConditionOutcome.MATCH, text="42")],
    )
    context = StepContext(result=result, task_variables={"limit": 10})

    assert resolve_binding('$result.children["ocr_a"].text', context) == "42"
    assert resolve_binding("$variables.task.limit", context) == 10


def test_binding_reads_all_variable_scopes():
    context = StepContext(
        task_variables={"task_value": 1},
        workflow_variables={"workflow_value": 2},
        persistent_variables={"persistent_value": 3},
    )

    assert resolve_binding("$variables.task.task_value", context) == 1
    assert resolve_binding("$variables.workflow.workflow_value", context) == 2
    assert resolve_binding("$variables.persistent.persistent_value", context) == 3


def test_missing_primary_is_a_binding_error():
    result = ConditionResult.and_group(
        "all",
        [ConditionResult(node_id="ocr_a", outcome=ConditionOutcome.MATCH)],
    )

    with pytest.raises(BindingError, match="primary"):
        resolve_binding("$result.primary.position", StepContext(result=result))


def test_missing_child_and_variable_report_the_failing_name():
    context = StepContext(result=ConditionResult(node_id="ocr_a", outcome=ConditionOutcome.MATCH))

    with pytest.raises(BindingError, match="image_b"):
        resolve_binding('$result.children["image_b"].position', context)
    with pytest.raises(BindingError, match="missing"):
        resolve_binding("$variables.task.missing", context)


def test_binding_parser_rejects_arbitrary_python():
    with pytest.raises(BindingError, match="unsupported"):
        resolve_binding("$result.__class__.__mro__", StepContext())

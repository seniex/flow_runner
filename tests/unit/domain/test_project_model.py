from uuid import uuid4

import pytest
from pydantic import ValidationError

from flow_runner.domain.enums import ConditionMode, StepOutcome
from flow_runner.domain.policies import ConditionPolicy
from flow_runner.domain.project import (
    AutomationStep,
    FlowGroup,
    ParallelBlock,
    Project,
    Workflow,
)
from flow_runner.domain.routing import ComparisonOperator, RoutePredicate, RouteRule, RouteTarget


def test_project_uses_stable_ids_and_cross_group_routes():
    target_workflow_id = uuid4()
    step = AutomationStep(
        name="进入 B",
        routes=[
            RouteRule(
                outcome=StepOutcome.SUCCESS,
                target=RouteTarget.jump_workflow(target_workflow_id),
            )
        ],
    )
    project = Project(
        name="挂机",
        groups=[FlowGroup(name="A", workflows=[Workflow(name="A1", steps=[step])])],
    )

    assert project.groups[0].workflows[0].steps[0].id == step.id
    assert step.routes[0].target.workflow_id == target_workflow_id


def test_once_policy_rejects_multiple_attempts():
    with pytest.raises(ValidationError, match="ONCE"):
        ConditionPolicy(mode=ConditionMode.ONCE, max_attempts=3)


def test_until_policy_requires_a_finite_limit():
    with pytest.raises(ValidationError, match="finite"):
        ConditionPolicy(
            mode=ConditionMode.UNTIL,
            max_attempts=None,
            timeout_seconds=None,
        )


def test_project_reports_broken_workflow_reference_without_mutation():
    missing_workflow_id = uuid4()
    route = RouteRule(
        outcome=StepOutcome.SUCCESS,
        target=RouteTarget.call_workflow(missing_workflow_id),
    )
    step = AutomationStep(name="调用缺失流程", routes=[route])
    project = Project(
        name="挂机",
        groups=[FlowGroup(name="A", workflows=[Workflow(name="A1", steps=[step])])],
    )

    errors = project.validate_references()

    assert errors == [
        f"workflow 'A1' step '调用缺失流程' references missing workflow {missing_workflow_id}"
    ]
    assert step.routes[0].target.workflow_id == missing_workflow_id


def test_project_rejects_duplicate_ids():
    duplicate_id = uuid4()
    project = Project(
        name="挂机",
        groups=[
            FlowGroup(name="A", workflows=[Workflow(id=duplicate_id, name="A1")]),
            FlowGroup(name="B", workflows=[Workflow(id=duplicate_id, name="B1")]),
        ],
    )

    assert project.validate_references() == [f"duplicate workflow id {duplicate_id}"]


def test_parallel_block_requires_explicit_unique_existing_workflows():
    first = Workflow(name="监控A")
    second = Workflow(name="监控B")
    project = Project(
        name="并行监控",
        groups=[FlowGroup(name="监控", workflows=[first, second])],
        parallel_blocks=[ParallelBlock(name="双监控", workflow_ids=[first.id, second.id])],
    )

    assert project.validate_references() == []
    with pytest.raises(ValidationError, match="at least 2"):
        ParallelBlock(name="无效", workflow_ids=[first.id])
    with pytest.raises(ValidationError, match="unique"):
        ParallelBlock(name="重复", workflow_ids=[first.id, first.id])


def test_project_reports_missing_count_predicate_references():
    missing_workflow = uuid4()
    missing_step = uuid4()
    step = AutomationStep(
        name="count route",
        routes=[
            RouteRule(
                outcome=StepOutcome.SUCCESS,
                predicate=RoutePredicate.workflow_count(
                    missing_workflow,
                    ComparisonOperator.GE,
                    1,
                ),
                target=RouteTarget.end(),
            ),
            RouteRule(
                outcome=StepOutcome.SUCCESS,
                predicate=RoutePredicate.step_count(
                    missing_step,
                    ComparisonOperator.GE,
                    1,
                ),
                target=RouteTarget.end(),
            ),
        ],
    )
    project = Project(
        name="p",
        groups=[FlowGroup(name="g", workflows=[Workflow(name="w", steps=[step])])],
    )

    errors = project.validate_references()

    assert any(f"missing workflow count reference {missing_workflow}" in error for error in errors)
    assert any(f"missing step count reference {missing_step}" in error for error in errors)


def test_project_reports_malformed_count_predicate_uuid():
    step = AutomationStep(
        name="bad count",
        routes=[
            RouteRule(
                outcome=StepOutcome.SUCCESS,
                predicate={
                    "source": "step_count",
                    "key": "not-a-uuid",
                    "operator": "eq",
                    "expected": 1,
                },
                target=RouteTarget.end(),
            )
        ],
    )
    project = Project(
        name="p",
        groups=[FlowGroup(name="g", workflows=[Workflow(name="w", steps=[step])])],
    )

    assert any(
        "invalid step_count UUID 'not-a-uuid'" in error for error in project.validate_references()
    )


def test_count_route_predicates_require_numeric_comparisons():
    with pytest.raises(ValidationError, match="numeric comparison"):
        RoutePredicate.workflow_count(
            uuid4(),
            ComparisonOperator.CONTAINS,
            1,
        )
    with pytest.raises(ValidationError, match="integer expected value"):
        RoutePredicate.model_validate(
            {
                "source": "step_count",
                "key": str(uuid4()),
                "operator": "eq",
                "expected": "3",
            }
        )

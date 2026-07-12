from uuid import uuid4

import pytest
from pydantic import ValidationError

from flow_runner.domain.enums import ConditionMode, StepOutcome
from flow_runner.domain.policies import ConditionPolicy
from flow_runner.domain.project import AutomationStep, FlowGroup, Project, Workflow
from flow_runner.domain.routing import RouteRule, RouteTarget


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
        f"workflow 'A1' step '调用缺失流程' references missing workflow "
        f"{missing_workflow_id}"
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

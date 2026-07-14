import importlib
from uuid import uuid4

from flow_runner.domain.enums import StepOutcome
from flow_runner.domain.project import AutomationStep, FlowGroup, Project, Workflow
from flow_runner.domain.routing import (
    ComparisonOperator,
    RoutePredicate,
    RouteRule,
    RouteTarget,
)


def test_clone_step_remaps_self_references_and_preserves_external_references():
    cloning = importlib.import_module("flow_runner.domain.cloning")
    external_step_id = uuid4()
    external_workflow_id = uuid4()
    step = AutomationStep(name="检测")
    step = step.model_copy(
        update={
            "routes": [
                RouteRule(
                    outcome=StepOutcome.SUCCESS,
                    predicate=RoutePredicate.step_count(
                        step.id,
                        ComparisonOperator.GE,
                        2,
                    ),
                    target=RouteTarget.next_step(step.id),
                ),
                RouteRule(
                    outcome=StepOutcome.FAILURE,
                    predicate=RoutePredicate.step_count(
                        external_step_id,
                        ComparisonOperator.EQ,
                        1,
                    ),
                    target=RouteTarget.jump_workflow(external_workflow_id),
                ),
            ]
        }
    )

    copied = cloning.clone_step(step)

    assert copied.id != step.id
    assert copied.name == "检测 副本"
    assert copied.routes[0].target.step_id == copied.id
    assert copied.routes[0].predicate.key == str(copied.id)
    assert copied.routes[1].target.workflow_id == external_workflow_id
    assert copied.routes[1].predicate.key == str(external_step_id)
    assert step.routes[0].target.step_id == step.id


def test_clone_workflow_remaps_internal_ids_and_keeps_external_workflow_targets():
    cloning = importlib.import_module("flow_runner.domain.cloning")
    first = AutomationStep(name="一")
    second = AutomationStep(name="二")
    external_workflow_id = uuid4()
    workflow = Workflow(name="流程", steps=[first, second])
    first = first.model_copy(
        update={
            "routes": [
                RouteRule(
                    outcome=StepOutcome.SUCCESS,
                    predicate=RoutePredicate.step_count(
                        second.id,
                        ComparisonOperator.EQ,
                        1,
                    ),
                    target=RouteTarget.next_step(second.id),
                ),
                RouteRule(
                    outcome=StepOutcome.TIMEOUT,
                    predicate=RoutePredicate.workflow_count(
                        workflow.id,
                        ComparisonOperator.GE,
                        2,
                    ),
                    target=RouteTarget.jump_workflow(workflow.id),
                ),
                RouteRule(
                    outcome=StepOutcome.FAILURE,
                    target=RouteTarget.jump_workflow(external_workflow_id),
                ),
            ]
        }
    )
    workflow = workflow.model_copy(update={"steps": [first, second]})

    copied = cloning.clone_workflow(workflow)

    assert copied.id != workflow.id
    assert copied.name == "流程 副本"
    assert [step.id for step in copied.steps] != [step.id for step in workflow.steps]
    assert [step.name for step in copied.steps] == ["一", "二"]
    assert copied.steps[0].routes[0].target.step_id == copied.steps[1].id
    assert copied.steps[0].routes[0].predicate.key == str(copied.steps[1].id)
    assert copied.steps[0].routes[1].target.workflow_id == copied.id
    assert copied.steps[0].routes[1].predicate.key == str(copied.id)
    assert copied.steps[0].routes[2].target.workflow_id == external_workflow_id


def test_clone_group_remaps_cross_workflow_references_and_validates_with_original():
    cloning = importlib.import_module("flow_runner.domain.cloning")
    first_step = AutomationStep(name="来源")
    second_step = AutomationStep(name="目标")
    first_workflow = Workflow(name="A", steps=[first_step])
    second_workflow = Workflow(name="B", steps=[second_step])
    external_workflow = Workflow(name="外部")
    first_step = first_step.model_copy(
        update={
            "routes": [
                RouteRule(
                    outcome=StepOutcome.SUCCESS,
                    predicate=RoutePredicate.step_count(
                        second_step.id,
                        ComparisonOperator.GT,
                        0,
                    ),
                    target=RouteTarget.jump_workflow(second_workflow.id),
                ),
                RouteRule(
                    outcome=StepOutcome.TIMEOUT,
                    predicate=RoutePredicate.workflow_count(
                        second_workflow.id,
                        ComparisonOperator.GE,
                        2,
                    ),
                    target=RouteTarget.jump_workflow(second_workflow.id),
                ),
                RouteRule(
                    outcome=StepOutcome.FAILURE,
                    predicate=RoutePredicate.workflow_count(
                        external_workflow.id,
                        ComparisonOperator.EQ,
                        1,
                    ),
                    target=RouteTarget.jump_workflow(external_workflow.id),
                ),
            ]
        }
    )
    first_workflow = first_workflow.model_copy(update={"steps": [first_step]})
    group = FlowGroup(name="组", workflows=[first_workflow, second_workflow])

    copied = cloning.clone_group(group)
    copied_first = copied.workflows[0].steps[0]
    copied_second = copied.workflows[1].steps[0]
    candidate = Project(
        name="p",
        groups=[
            group,
            copied,
            FlowGroup(name="外部组", workflows=[external_workflow]),
        ],
    )

    assert copied.id != group.id
    assert copied.name == "组 副本"
    assert copied.workflows[0].id != first_workflow.id
    assert copied_first.routes[0].target.workflow_id == copied.workflows[1].id
    assert copied_first.routes[0].predicate.key == str(copied_second.id)
    assert copied_first.routes[1].predicate.key == str(copied.workflows[1].id)
    assert copied_first.routes[2].target.workflow_id == external_workflow.id
    assert copied_first.routes[2].predicate.key == str(external_workflow.id)
    assert candidate.validate_references() == []

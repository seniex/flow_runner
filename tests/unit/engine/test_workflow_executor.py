from uuid import UUID

import pytest

from flow_runner.domain.enums import StepOutcome
from flow_runner.domain.errors import RoutingError
from flow_runner.domain.project import AutomationStep, FlowGroup, Project, Workflow
from flow_runner.domain.results import StepResult
from flow_runner.domain.routing import (
    ComparisonOperator,
    RoutePredicate,
    RouteRule,
    RouteTarget,
)
from flow_runner.engine.context import StepContext, TaskContext, WorkflowContext
from flow_runner.engine.workflow_executor import WorkflowExecutor


class SuccessfulStepExecutor:
    def __init__(self):
        self.step_names = []

    async def execute(self, step):
        self.step_names.append(step.name)
        return StepResult(outcome=StepOutcome.SUCCESS)


class OutcomeStepExecutor:
    def __init__(self, outcomes):
        self.outcomes = iter(outcomes)
        self.step_names = []

    async def execute(self, step):
        self.step_names.append(step.name)
        return StepResult(outcome=next(self.outcomes))


def workflow(name, target=None, routes=None):
    step = AutomationStep(
        name=name,
        routes=routes
        or ([RouteRule(outcome=StepOutcome.SUCCESS, target=target)] if target else []),
    )
    return Workflow(name=name, steps=[step])


@pytest.mark.asyncio
async def test_dynamic_cross_group_route_reaches_c1():
    ids = {
        name: UUID(int=index + 1)
        for index, name in enumerate(("A1", "A2", "A3", "B1", "B2", "B3", "C1"))
    }
    a1 = workflow("A1", RouteTarget.jump_workflow(ids["A2"])).model_copy(update={"id": ids["A1"]})
    a2 = workflow("A2", RouteTarget.jump_workflow(ids["A3"])).model_copy(update={"id": ids["A2"]})
    a3 = workflow(
        "A3",
        routes=[
            RouteRule(
                outcome=StepOutcome.SUCCESS,
                predicate=RoutePredicate.workflow_count(ids["A1"], ComparisonOperator.LT, 3),
                target=RouteTarget.jump_workflow(ids["A1"]),
            ),
            RouteRule(
                outcome=StepOutcome.SUCCESS,
                target=RouteTarget.jump_workflow(ids["B1"]),
            ),
        ],
    ).model_copy(update={"id": ids["A3"]})
    b1 = workflow("B1", RouteTarget.jump_workflow(ids["B2"])).model_copy(update={"id": ids["B1"]})
    b2 = workflow("B2", RouteTarget.jump_workflow(ids["B3"])).model_copy(update={"id": ids["B2"]})
    b3 = workflow("B3", RouteTarget.jump_workflow(ids["C1"])).model_copy(update={"id": ids["B3"]})
    c1 = workflow("C1", RouteTarget.end()).model_copy(update={"id": ids["C1"]})
    project = Project(
        name="挂机",
        groups=[
            FlowGroup(name="A", workflows=[a1, a2, a3]),
            FlowGroup(name="B", workflows=[b1, b2, b3]),
            FlowGroup(name="C", workflows=[c1]),
        ],
    )
    steps = SuccessfulStepExecutor()

    trace = await WorkflowExecutor(project, steps).run(ids["A1"])

    assert trace.workflow_names == (
        "A1",
        "A2",
        "A3",
        "A1",
        "A2",
        "A3",
        "A1",
        "A2",
        "A3",
        "B1",
        "B2",
        "B3",
        "C1",
    )
    assert steps.step_names == list(trace.workflow_names)


@pytest.mark.asyncio
async def test_non_success_without_matching_route_stops_instead_of_implicit_ignore():
    first = AutomationStep(name="first")
    second = AutomationStep(name="second")
    workflow = Workflow(name="main", steps=[first, second])
    project = Project(name="p", groups=[FlowGroup(name="g", workflows=[workflow])])
    steps = OutcomeStepExecutor([StepOutcome.FAILURE, StepOutcome.SUCCESS])

    trace = await WorkflowExecutor(project, steps).run(workflow.id)

    assert trace.step_names == ("first",)
    assert trace.terminal_outcome is StepOutcome.FAILURE


@pytest.mark.asyncio
async def test_explicit_failure_route_can_continue_to_another_step():
    second = AutomationStep(name="second")
    first = AutomationStep(
        name="first",
        routes=[
            RouteRule(
                outcome=StepOutcome.FAILURE,
                target=RouteTarget.next_step(second.id),
            )
        ],
    )
    workflow = Workflow(name="main", steps=[first, second])
    project = Project(name="p", groups=[FlowGroup(name="g", workflows=[workflow])])
    steps = OutcomeStepExecutor([StepOutcome.FAILURE, StepOutcome.SUCCESS])

    trace = await WorkflowExecutor(project, steps).run(workflow.id)

    assert trace.step_names == ("first", "second")
    assert trace.terminal_outcome is StepOutcome.SUCCESS


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operator", "expected"),
    [
        (ComparisonOperator.CONTAINS, "ready"),
        (ComparisonOperator.MATCHES, r"^battle_.*_ready$"),
    ],
)
async def test_text_route_predicates_select_matching_branch(operator, expected):
    matched = workflow("matched", RouteTarget.end())
    fallback = workflow("fallback", RouteTarget.end())
    entry = workflow(
        "entry",
        routes=[
            RouteRule(
                outcome=StepOutcome.SUCCESS,
                predicate=RoutePredicate.task_variable("state", operator, expected),
                target=RouteTarget.jump_workflow(matched.id),
            ),
            RouteRule(
                outcome=StepOutcome.SUCCESS,
                target=RouteTarget.jump_workflow(fallback.id),
            ),
        ],
    )
    project = Project(
        name="text route",
        groups=[FlowGroup(name="g", workflows=[entry, matched, fallback])],
    )

    trace = await WorkflowExecutor(
        project,
        SuccessfulStepExecutor(),
        task_context=TaskContext(task_variables={"state": "battle_team_ready"}),
    ).run(entry.id)

    assert trace.workflow_names == ("entry", "matched")


@pytest.mark.asyncio
async def test_invalid_route_regex_is_reported_as_routing_error():
    entry = workflow(
        "entry",
        routes=[
            RouteRule(
                outcome=StepOutcome.SUCCESS,
                predicate=RoutePredicate.task_variable(
                    "state",
                    ComparisonOperator.MATCHES,
                    "[",
                ),
                target=RouteTarget.end(),
            )
        ],
    )
    project = Project(name="invalid regex", groups=[FlowGroup(name="g", workflows=[entry])])

    with pytest.raises(RoutingError, match="matches"):
        await WorkflowExecutor(
            project,
            SuccessfulStepExecutor(),
            task_context=TaskContext(task_variables={"state": "ready"}),
        ).run(entry.id)


@pytest.mark.asyncio
async def test_call_and_return_resume_the_callers_next_step():
    child = Workflow(
        name="child",
        steps=[
            AutomationStep(
                name="child-step",
                routes=[
                    RouteRule(
                        outcome=StepOutcome.SUCCESS,
                        target=RouteTarget.return_to_caller(),
                    )
                ],
            )
        ],
    )
    caller_last = AutomationStep(
        name="caller-last",
        routes=[RouteRule(outcome=StepOutcome.SUCCESS, target=RouteTarget.end())],
    )
    caller = Workflow(
        name="caller",
        steps=[
            AutomationStep(
                name="caller-first",
                routes=[
                    RouteRule(
                        outcome=StepOutcome.SUCCESS,
                        target=RouteTarget.call_workflow(child.id),
                    )
                ],
            ),
            caller_last,
        ],
    )
    project = Project(
        name="calls",
        groups=[FlowGroup(name="flows", workflows=[caller, child])],
    )
    steps = SuccessfulStepExecutor()

    trace = await WorkflowExecutor(project, steps).run(caller.id)

    assert trace.step_names == ("caller-first", "child-step", "caller-last")


@pytest.mark.asyncio
async def test_return_without_a_caller_is_a_routing_error():
    orphan = workflow("orphan", RouteTarget.return_to_caller())
    project = Project(name="orphan", groups=[FlowGroup(name="g", workflows=[orphan])])

    with pytest.raises(RoutingError, match="call stack"):
        await WorkflowExecutor(project, SuccessfulStepExecutor()).run(orphan.id)


@pytest.mark.asyncio
async def test_transition_limit_stops_a_busy_route_loop():
    loop = workflow("loop")
    loop = loop.model_copy(
        update={
            "steps": [
                loop.steps[0].model_copy(
                    update={
                        "routes": [
                            RouteRule(
                                outcome=StepOutcome.SUCCESS,
                                target=RouteTarget.jump_workflow(loop.id),
                            )
                        ]
                    }
                )
            ]
        }
    )
    project = Project(name="loop", groups=[FlowGroup(name="g", workflows=[loop])])

    with pytest.raises(RoutingError, match="transition limit"):
        await WorkflowExecutor(
            project,
            SuccessfulStepExecutor(),
            transition_limit=5,
        ).run(loop.id)


@pytest.mark.asyncio
async def test_executor_context_switches_workflow_variables_and_shares_runtime_counts():
    second = workflow("B", RouteTarget.end())
    first = workflow("A", RouteTarget.jump_workflow(second.id))
    project = Project(
        name="contexts",
        groups=[FlowGroup(name="g", workflows=[first, second])],
    )

    class ContextAwareExecutor:
        def __init__(self):
            self.context = StepContext()
            self.observations = []

        def bind_workflow_context(self, context: WorkflowContext):
            self.context = StepContext.from_workflow(context)

        async def execute(self, step):
            self.observations.append(
                {
                    "name": step.name,
                    "workflow_variables": dict(self.context.workflow_variables),
                    "workflow_counts": dict(self.context.workflow_counts),
                    "step_counts": dict(self.context.step_counts),
                }
            )
            if step.name == "A":
                self.context.workflow_variables["local"] = "A-only"
            return StepResult(outcome=StepOutcome.SUCCESS)

    executor = ContextAwareExecutor()

    await WorkflowExecutor(project, executor).run(first.id)

    first_observation, second_observation = executor.observations
    assert first_observation["workflow_counts"] == {first.id: 1}
    assert first_observation["step_counts"] == {first.steps[0].id: 1}
    assert second_observation["workflow_counts"] == {first.id: 1, second.id: 1}
    assert "local" not in second_observation["workflow_variables"]

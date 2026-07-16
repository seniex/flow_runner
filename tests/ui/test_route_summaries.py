from flow_runner.display_labels import ProjectDisplayIndex
from flow_runner.domain.enums import StepOutcome
from flow_runner.domain.project import AutomationStep, FlowGroup, Project, Workflow
from flow_runner.domain.routing import (
    ComparisonOperator,
    RoutePredicate,
    RouteRule,
    RouteTarget,
)
from flow_runner.ui.route_summaries import format_route_summaries


def test_route_summaries_include_numbered_target_and_count_predicate():
    target_step = AutomationStep(name="目标步骤")
    target_workflow = Workflow(name="目标流程", steps=[target_step])
    source_step = AutomationStep(name="来源")
    source_workflow = Workflow(name="来源流程", steps=[source_step])
    project = Project(
        name="p",
        groups=[FlowGroup(name="组", workflows=[source_workflow, target_workflow])],
    )
    route = RouteRule(
        outcome=StepOutcome.FAILURE,
        predicate=RoutePredicate.step_count(target_step.id, ComparisonOperator.GE, 3),
        target=RouteTarget.jump_workflow(target_workflow.id),
    )

    assert format_route_summaries(
        [route],
        labels=ProjectDisplayIndex(project),
    ) == (
        "路由 1：失败 且 01. 组 / 02. 目标流程 / 01. 目标步骤执行次数 >= 3 "
        "→ 跳转流程：01. 组 / 02. 目标流程 / 01. 目标步骤",
    )


def test_route_summaries_put_each_route_on_its_own_line_and_mark_otherwise():
    routes = [
        RouteRule(
            outcome=StepOutcome.SUCCESS,
            predicate=RoutePredicate.task_variable("ready", ComparisonOperator.EQ, True),
            target=RouteTarget.end(),
        ),
        RouteRule(outcome=StepOutcome.SUCCESS, target=RouteTarget.end()),
    ]

    assert format_route_summaries(
        routes,
        labels=ProjectDisplayIndex(Project(name="p")),
    ) == (
        "路由 1：成功 且 任务变量 ready = true → 结束任务",
        "路由 2：成功（否则） → 结束任务",
    )


def test_empty_route_summary_describes_implicit_behavior():
    assert format_route_summaries(
        [],
        labels=ProjectDisplayIndex(Project(name="p")),
    ) == ("路由：成功时顺序进入下一步骤；其它结果结束",)

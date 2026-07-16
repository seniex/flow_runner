import json
from collections.abc import Mapping, Sequence
from uuid import UUID

from flow_runner.display_labels import ProjectDisplayIndex
from flow_runner.domain.routing import RoutePredicate, RouteRule, RouteTarget, RouteTargetKind
from flow_runner.ui.localization import choice_label, comparison_symbol


def format_route_summaries(
    routes: Sequence[RouteRule],
    *,
    labels: ProjectDisplayIndex,
    binding_labels: Mapping[str, str] | None = None,
) -> tuple[str, ...]:
    if not routes:
        return ("路由：成功时顺序进入下一步骤；其它结果结束",)
    summaries: list[str] = []
    for index, route in enumerate(routes):
        detail = format_route_summary(
            route,
            index,
            routes,
            labels=labels,
            binding_labels=binding_labels,
        )
        summaries.append(f"路由 {index + 1}：{detail}")
    return tuple(summaries)


def format_route_summary(
    route: RouteRule,
    index: int,
    routes: Sequence[RouteRule],
    *,
    labels: ProjectDisplayIndex,
    binding_labels: Mapping[str, str] | None = None,
) -> str:
    outcome = choice_label(route.outcome)
    if route.predicate is None and any(
        previous.outcome == route.outcome and previous.predicate is not None
        for previous in routes[:index]
    ):
        outcome += "（否则）"
    predicate = (
        f" 且 {_predicate_summary(route.predicate, labels, binding_labels)}"
        if route.predicate is not None
        else ""
    )
    return f"{outcome}{predicate} → {_target_summary(route.target, labels)}"


def _predicate_summary(
    predicate: RoutePredicate,
    labels: ProjectDisplayIndex,
    binding_labels: Mapping[str, str] | None,
) -> str:
    if predicate.source == "workflow_count":
        subject = f"{_workflow_path(predicate.key, labels)}执行次数"
    elif predicate.source == "step_count":
        subject = f"{_step_path(predicate.key, labels)}执行次数"
    elif predicate.source == "binding":
        subject = (
            binding_labels.get(predicate.key, predicate.key)
            if binding_labels is not None
            else predicate.key
        )
    elif predicate.source == "task_variable":
        subject = f"任务变量 {predicate.key}"
    else:
        subject = f"流程变量 {predicate.key}"
    expected = json.dumps(predicate.expected, ensure_ascii=False)
    return f"{subject} {comparison_symbol(predicate.operator)} {expected}"


def _target_summary(target: RouteTarget, labels: ProjectDisplayIndex) -> str:
    if target.kind is RouteTargetKind.NEXT_STEP and target.step_id is not None:
        return f"下一步骤：{labels.step_path(target.step_id)}"
    if target.kind is RouteTargetKind.JUMP_WORKFLOW and target.workflow_id is not None:
        return f"跳转流程：{labels.workflow_entry_path(target.workflow_id)}"
    if target.kind is RouteTargetKind.CALL_WORKFLOW and target.workflow_id is not None:
        return f"调用流程：{labels.workflow_entry_path(target.workflow_id)}"
    return choice_label(target.kind)


def _workflow_path(value: object, labels: ProjectDisplayIndex) -> str:
    try:
        return labels.workflow_path(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return "未知流程"


def _step_path(value: object, labels: ProjectDisplayIndex) -> str:
    try:
        return labels.step_path(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return "未知步骤"

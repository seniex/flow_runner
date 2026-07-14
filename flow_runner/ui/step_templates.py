from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID

from flow_runner.domain.actions import ActionSpec
from flow_runner.domain.conditions import LeafCondition
from flow_runner.domain.enums import ConditionMode, StepOutcome
from flow_runner.domain.policies import ConditionPolicy
from flow_runner.domain.project import AutomationStep, Project, Workflow
from flow_runner.domain.routing import ComparisonOperator, RoutePredicate, RouteRule, RouteTarget


@dataclass(frozen=True, slots=True)
class StepTemplate:
    name: str
    parameters: tuple[str, ...]


STEP_TEMPLATES: dict[str, StepTemplate] = {
    "ocr_click": StepTemplate("OCR 检测到文字后点击", ("keywords",)),
    "ocr_timeout_continue": StepTemplate(
        "OCR 持续检测，超时后继续",
        ("keywords", "timeout_seconds", "target_step_id"),
    ),
    "wait_then_key": StepTemplate("固定等待后发送按键", ("seconds", "key")),
    "activate_window_then_key": StepTemplate(
        "激活窗口后发送按键",
        ("window_title", "key"),
    ),
    "jump_after_two_runs": StepTemplate(
        "执行两轮后跳转到另一流程",
        ("target_workflow_id",),
    ),
    "success_timeout_branches": StepTemplate(
        "成功和超时进入不同流程",
        ("success_workflow_id", "timeout_workflow_id"),
    ),
}


def build_template_step(
    template_id: str,
    parameters: Mapping[str, object],
    *,
    project: Project,
    current_workflow_id: UUID,
) -> AutomationStep:
    try:
        template = STEP_TEMPLATES[template_id]
    except KeyError:
        raise ValueError(f"未知步骤模板：{template_id}") from None
    current_workflow = _workflow(project, current_workflow_id)
    name = _optional_text(parameters, "name") or template.name

    if template_id == "ocr_click":
        return AutomationStep(
            name=name,
            condition=_ocr_condition(_required_text(parameters, "keywords")),
            actions=[
                ActionSpec(
                    capability="input.mouse",
                    config={"operation": "click", "position": "$result.primary.position"},
                )
            ],
        )
    if template_id == "ocr_timeout_continue":
        target_step_id = _required_uuid(parameters, "target_step_id")
        if all(step.id != target_step_id for step in current_workflow.steps):
            raise ValueError("目标步骤不在当前流程中")
        return AutomationStep(
            name=name,
            condition=_ocr_condition(_required_text(parameters, "keywords")),
            condition_policy=ConditionPolicy(
                mode=ConditionMode.UNTIL,
                max_attempts=None,
                timeout_seconds=_positive_number(parameters, "timeout_seconds"),
            ),
            routes=[
                RouteRule(
                    outcome=StepOutcome.TIMEOUT,
                    target=RouteTarget.next_step(target_step_id),
                )
            ],
        )
    if template_id == "wait_then_key":
        return AutomationStep(
            name=name,
            actions=[
                ActionSpec(
                    capability="system.wait",
                    config={"seconds": _non_negative_number(parameters, "seconds")},
                ),
                _key_action(_required_text(parameters, "key")),
            ],
        )
    if template_id == "activate_window_then_key":
        return AutomationStep(
            name=name,
            actions=[
                ActionSpec(
                    capability="system.window_action",
                    config={
                        "operation": "activate",
                        "title": _required_text(parameters, "window_title"),
                    },
                ),
                _key_action(_required_text(parameters, "key")),
            ],
        )
    if template_id == "jump_after_two_runs":
        target_workflow_id = _existing_workflow_id(project, parameters, "target_workflow_id")
        return AutomationStep(
            name=name,
            routes=[
                RouteRule(
                    outcome=StepOutcome.SUCCESS,
                    predicate=RoutePredicate.workflow_count(
                        current_workflow_id,
                        ComparisonOperator.GE,
                        2,
                    ),
                    target=RouteTarget.jump_workflow(target_workflow_id),
                )
            ],
        )
    success_workflow_id = _existing_workflow_id(project, parameters, "success_workflow_id")
    timeout_workflow_id = _existing_workflow_id(project, parameters, "timeout_workflow_id")
    return AutomationStep(
        name=name,
        routes=[
            RouteRule(
                outcome=StepOutcome.SUCCESS,
                target=RouteTarget.jump_workflow(success_workflow_id),
            ),
            RouteRule(
                outcome=StepOutcome.TIMEOUT,
                target=RouteTarget.jump_workflow(timeout_workflow_id),
            ),
        ],
    )


def _ocr_condition(keywords: str) -> LeafCondition:
    return LeafCondition(
        id="ocr",
        capability="vision.ocr",
        config={"keywords": keywords},
    )


def _key_action(key: str) -> ActionSpec:
    return ActionSpec(capability="input.keyboard", config={"operation": "press", "key": key})


def _workflow(project: Project, workflow_id: UUID) -> Workflow:
    for group in project.groups:
        for workflow in group.workflows:
            if workflow.id == workflow_id:
                return workflow
    raise ValueError("当前流程不存在")


def _existing_workflow_id(
    project: Project,
    parameters: Mapping[str, object],
    name: str,
) -> UUID:
    workflow_id = _required_uuid(parameters, name)
    if all(workflow.id != workflow_id for group in project.groups for workflow in group.workflows):
        raise ValueError("目标流程不存在")
    return workflow_id


def _required_uuid(parameters: Mapping[str, object], name: str) -> UUID:
    value = parameters.get(name)
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise ValueError(f"参数 {name} 必须选择有效目标") from None


def _required_text(parameters: Mapping[str, object], name: str) -> str:
    value = _optional_text(parameters, name)
    if not value:
        raise ValueError(f"参数 {name} 不能为空")
    return value


def _optional_text(parameters: Mapping[str, object], name: str) -> str:
    value = parameters.get(name, "")
    return str(value).strip() if value is not None else ""


def _positive_number(parameters: Mapping[str, object], name: str) -> float:
    value = _number(parameters, name)
    if value <= 0:
        raise ValueError(f"参数 {name} 必须大于 0")
    return value


def _non_negative_number(parameters: Mapping[str, object], name: str) -> float:
    value = _number(parameters, name)
    if value < 0:
        raise ValueError(f"参数 {name} 不能小于 0")
    return value


def _number(parameters: Mapping[str, object], name: str) -> float:
    value = parameters.get(name)
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError(f"参数 {name} 必须是数字")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"参数 {name} 必须是数字") from None

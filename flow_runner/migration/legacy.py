from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from flow_runner.domain.actions import ActionSpec
from flow_runner.domain.conditions import LeafCondition
from flow_runner.domain.enums import ConditionMode, StepOutcome
from flow_runner.domain.policies import ConditionPolicy
from flow_runner.domain.project import AutomationStep, FlowGroup, Project, Workflow
from flow_runner.domain.routing import ComparisonOperator, RoutePredicate, RouteRule, RouteTarget
from flow_runner.infrastructure.input.recording import RecordedEvent
from flow_runner.migration.window_controls import replacement_actions_for_script

_NAMESPACE = UUID("52ca7442-748d-5ac3-bf51-d59a13bc76b3")


@dataclass(frozen=True, slots=True)
class LegacyConversionPaths:
    project_directory: Path
    python_executable: Path
    pythonw_executable: Path
    paddle_executable: Path
    recording_directory: Path


def convert_legacy_config(
    source: dict[str, Any],
    paths: LegacyConversionPaths,
) -> Project:
    legacy_groups = list(source.get("flow_groups", []))
    workflow_ids = {
        (group_index, flow_index): _stable_id(
            f"workflow:{group_index}:{flow_index}:{flow.get('name', '')}"
        )
        for group_index, group in enumerate(legacy_groups)
        for flow_index, flow in enumerate(group.get("flows", []))
    }
    groups: list[FlowGroup] = []
    for group_index, legacy_group in enumerate(legacy_groups):
        workflows: list[Workflow] = []
        legacy_flows = list(legacy_group.get("flows", []))
        for flow_index, legacy_flow in enumerate(legacy_flows):
            steps = [
                _convert_step(step, paths, group_index, flow_index, step_index)
                for step_index, step in enumerate(legacy_flow.get("steps", []))
            ]
            workflow = Workflow(
                id=workflow_ids[(group_index, flow_index)],
                name=str(legacy_flow.get("name") or f"流程{flow_index + 1}"),
                steps=steps,
            )
            workflows.append(workflow)
        workflows = _apply_routes(legacy_flows, workflows, workflow_ids, group_index)
        groups.append(
            FlowGroup(
                id=_stable_id(f"group:{group_index}:{legacy_group.get('name', '')}"),
                name=str(legacy_group.get("name") or f"流程组{group_index + 1}"),
                workflows=workflows,
            )
        )

    settings = {
        "ocr_engine": str(source.get("ocr_engine", "paddle")),
        "paddle_exe_path": str(paths.paddle_executable.resolve()),
        "window_capture_mode": "foreground",
        "window_capture_fallback": True,
        "window_capture_timeout_seconds": 3.0,
        "hotkeys": {
            "start": str(source.get("hotkey_start", "F6")),
            "stop": str(source.get("hotkey_stop", "F7")),
            "pause": str(source.get("hotkey_pause", "F8")),
            "record": str(source.get("hotkey_rec_toggle", "F9")),
        },
        "legacy_conversion": {
            "source": "config/flow_runner.json",
            "workflow_count": sum(len(group.workflows) for group in groups),
            "step_count": sum(
                len(workflow.steps) for group in groups for workflow in group.workflows
            ),
        },
    }
    return Project(
        id=_stable_id("project:legacy-flow-runner"),
        name="旧版挂机配置（已转换）",
        groups=groups,
        settings=settings,
    )


def convert_legacy_recording(events: list[dict[str, Any]]) -> list[RecordedEvent]:
    if not events:
        return []
    baseline = float(events[0].get("t", 0.0))
    converted: list[RecordedEvent] = []
    for event in events:
        timestamp = max(0.0, float(event.get("t", baseline)) - baseline)
        event_type = str(event.get("type", ""))
        if event_type == "move":
            converted.append(
                RecordedEvent(
                    timestamp=timestamp,
                    kind="move",
                    data={"x": int(event["x"]), "y": int(event["y"])},
                )
            )
        elif event_type == "click" and bool(event.get("down", True)):
            converted.append(
                RecordedEvent(
                    timestamp=timestamp,
                    kind="click",
                    data={
                        "x": int(event["x"]),
                        "y": int(event["y"]),
                        "button": str(event.get("btn", "left")),
                    },
                )
            )
        elif event_type == "scroll":
            vertical = int(event.get("dy", 0))
            if vertical:
                converted.append(
                    RecordedEvent(
                        timestamp=timestamp,
                        kind="scroll",
                        data={
                            "x": int(event["x"]),
                            "y": int(event["y"]),
                            "units": vertical * 120,
                        },
                    )
                )
        elif event_type == "key" and str(event.get("key", "")):
            converted.append(
                RecordedEvent(
                    timestamp=timestamp,
                    kind="key_press" if bool(event.get("down", True)) else "key_release",
                    data={"key": str(event["key"])},
                )
            )
    return converted


def _convert_step(
    legacy: dict[str, Any],
    paths: LegacyConversionPaths,
    group_index: int,
    flow_index: int,
    step_index: int,
) -> AutomationStep:
    step_type = str(legacy.get("type", ""))
    step_id = _stable_id(
        f"step:{group_index}:{flow_index}:{step_index}:{legacy.get('name', step_type)}"
    )
    name = str(legacy.get("name") or step_type or f"步骤{step_index + 1}")
    if step_type in {
        "ocr_click",
        "ocr_loop",
        "ocr_poll",
        "img_click",
        "img_loop",
        "img_poll",
    }:
        return _convert_condition_step(legacy, paths, step_id, name)
    return AutomationStep(
        id=step_id,
        name=name,
        actions=_convert_action_step(legacy, paths),
    )


def _convert_condition_step(
    legacy: dict[str, Any],
    paths: LegacyConversionPaths,
    step_id: UUID,
    name: str,
) -> AutomationStep:
    step_type = str(legacy["type"])
    is_ocr = step_type.startswith("ocr_")
    condition = LeafCondition(
        id="detector",
        capability="vision.ocr" if is_ocr else "vision.image",
        config=(
            {
                "target": "desktop",
                "region": legacy.get("region"),
                "keywords": str(legacy.get("keywords", "")),
                "language": str(legacy.get("language", "chi_sim")),
                "scale": float(legacy.get("ocr_scale", 1)),
            }
            if is_ocr
            else {
                "target": "desktop",
                "region": legacy.get("region"),
                "template_path": str(_project_asset_path(legacy.get("template_path"), paths)),
                "threshold": float(legacy.get("threshold", 80)) / 100,
            }
        ),
    )
    loop_style = step_type in {"ocr_loop", "img_loop"}
    poll_style = step_type in {"ocr_poll", "img_poll"}
    if loop_style:
        attempts = int(legacy.get("max_retries", 10)) + 1
        interval = 0.0
        before_actions = _convert_pre_action(legacy.get("pre_action"), paths)
        before_actions.append(_wait_action(float(legacy.get("check_interval", 1.0))))
    elif poll_style:
        attempts = int(legacy.get("max_count", 60))
        interval = float(legacy.get("interval", 1.0))
        before_actions = []
    else:
        attempts = int(legacy.get("max_retries", 30)) + 1
        interval = float(legacy.get("retry_interval", 1.0))
        before_actions = []
    click_on_match = not loop_style and not poll_style or bool(legacy.get("click_on_match", False))
    jitter = bool(legacy.get("jitter", True))
    actions = (
        _convert_click_actions(legacy.get("click_actions", []), jitter=jitter)
        if click_on_match
        else []
    )
    return AutomationStep(
        id=step_id,
        name=name,
        condition=condition,
        actions=actions,
        condition_policy=ConditionPolicy(
            mode=ConditionMode.UNTIL,
            interval_seconds=interval,
            max_attempts=attempts,
            before_attempt_actions=before_actions,
        ),
    )


def _convert_action_step(
    legacy: dict[str, Any],
    paths: LegacyConversionPaths,
) -> list[ActionSpec]:
    step_type = str(legacy.get("type", ""))
    if step_type == "wait":
        return [_wait_action(float(legacy.get("seconds", 1.0)))]
    if step_type == "mouse_move":
        return [
            _mouse_action(
                "move",
                [int(legacy.get("x", 0)), int(legacy.get("y", 0))],
                duration=float(legacy.get("duration", 0.3)),
            )
        ]
    if step_type == "scroll":
        return _convert_scroll_actions(legacy)
    if step_type == "keyboard":
        return _convert_keyboard_actions(legacy.get("key_actions", []))
    if step_type == "run_script":
        name = Path(str(legacy.get("script_path", "recording.json"))).name
        target = paths.recording_directory / name
        return [
            ActionSpec(
                capability="recording.playback",
                config={
                    "path": str(_relative_or_absolute(target, paths.project_directory)),
                    "speed": float(legacy.get("speed", 1.0)),
                    "max_gap": float(legacy.get("max_gap", 2.0)),
                    "jitter_ms": int(legacy.get("jitter_ms", 0)),
                },
            )
        ]
    if step_type == "launch_app":
        return _convert_launch_actions(legacy, paths)
    raise ValueError(f"unsupported legacy step type: {step_type}")


def _convert_click_actions(raw_actions: Any, *, jitter: bool) -> list[ActionSpec]:
    result: list[ActionSpec] = []
    for raw in raw_actions or []:
        pre_delay = float(raw.get("pre_delay", 0.0))
        if pre_delay > 0:
            result.append(_wait_action(pre_delay))
        mode = str(raw.get("pos_mode", "match_center"))
        if mode == "abs":
            position: Any = [int(raw.get("abs_x", 0)), int(raw.get("abs_y", 0))]
            offset = [0, 0]
        else:
            position = "$result.primary.position"
            offset = (
                [int(raw.get("offset_x", 0)), int(raw.get("offset_y", 0))]
                if mode == "offset"
                else [0, 0]
            )
        count = int(raw.get("count", 1))
        click_type = str(raw.get("click_type", "single"))
        if count <= 0:
            result.append(
                _mouse_action(
                    "move",
                    position,
                    offset=offset,
                    duration=0.015,
                    jitter_pixels=3 if jitter else 0,
                )
            )
            result.append(_wait_action(0.015))
            continue
        result.append(
            _mouse_action(
                "click",
                position,
                offset=offset,
                button="right" if click_type == "right" else "left",
                clicks=count * (2 if click_type == "double" else 1),
                interval=float(raw.get("interval", 0.1)),
                jitter_pixels=3 if jitter else 0,
                duration=0.015,
                settle_delay=0.015,
            )
        )
    return result


def _convert_scroll_actions(legacy: dict[str, Any]) -> list[ActionSpec]:
    direction = 1 if str(legacy.get("direction", "up")) == "up" else -1
    raw_delta = direction * max(1, int(120 * float(legacy.get("delta_mul", 3))))
    actions: list[ActionSpec] = []
    clicks = max(1, int(legacy.get("clicks", 1)))
    for index in range(clicks):
        actions.append(
            _mouse_action(
                "scroll",
                [int(legacy.get("x", 0)), int(legacy.get("y", 0))],
                scroll_units=raw_delta,
            )
        )
        if index + 1 < clicks and float(legacy.get("interval", 0.1)) > 0:
            actions.append(_wait_action(float(legacy.get("interval", 0.1))))
    return actions


def _convert_keyboard_actions(raw_actions: Any) -> list[ActionSpec]:
    actions: list[ActionSpec] = []
    for raw in raw_actions or []:
        keys = [part.strip() for part in str(raw.get("key", "")).split("+") if part.strip()]
        if not keys:
            continue
        operation = str(raw.get("action", "press"))
        count = max(1, int(raw.get("count", 1)))
        interval = float(raw.get("interval", 0.05))
        if operation == "press":
            config = (
                {"operation": "hotkey", "keys": keys}
                if len(keys) > 1
                else {
                    "operation": "press",
                    "key": keys[0],
                    "count": count,
                    "interval": interval,
                }
            )
            actions.append(ActionSpec(capability="input.keyboard", config=config))
        else:
            ordered = keys if operation == "down" else list(reversed(keys))
            for key in ordered:
                actions.append(
                    ActionSpec(
                        capability="input.keyboard",
                        config={
                            "operation": "key_down" if operation == "down" else "key_up",
                            "key": key,
                        },
                    )
                )
    return actions


def _convert_launch_actions(
    legacy: dict[str, Any],
    paths: LegacyConversionPaths,
) -> list[ActionSpec]:
    application = Path(str(legacy.get("app_path", "")))
    replacement = replacement_actions_for_script(application)
    if replacement is not None:
        actions = list(replacement)
        wait_seconds = float(legacy.get("wait_seconds", 0.0))
        if wait_seconds > 0:
            actions.append(_wait_action(wait_seconds))
        return actions
    suffix = application.suffix.casefold()
    if suffix in {".py", ".pyw"}:
        executable = paths.pythonw_executable if suffix == ".pyw" else paths.python_executable
        path = executable
        arguments = [str(application)]
        run_as_admin = False
    else:
        path = application
        arguments = []
        run_as_admin = bool(legacy.get("run_as_admin", False))
    actions = [
        ActionSpec(
            capability="system.launch",
            config={
                "path": str(path),
                "arguments": arguments,
                "run_as_admin": run_as_admin,
                "working_directory": str(application.parent),
                "hide_window": suffix in {".py", ".pyw"},
            },
        )
    ]
    wait_seconds = float(legacy.get("wait_seconds", 0.0))
    if wait_seconds > 0:
        actions.append(_wait_action(wait_seconds))
    return actions


def _convert_pre_action(raw: Any, paths: LegacyConversionPaths) -> list[ActionSpec]:
    if not isinstance(raw, dict):
        return []
    return _convert_action_step(raw, paths)


def _apply_routes(
    legacy_flows: list[dict[str, Any]],
    workflows: list[Workflow],
    workflow_ids: dict[tuple[int, int], UUID],
    group_index: int,
) -> list[Workflow]:
    result: list[Workflow] = []
    for _flow_index, (legacy, workflow) in enumerate(zip(legacy_flows, workflows, strict=True)):
        if not workflow.steps:
            result.append(workflow)
            continue
        steps = list(workflow.steps)
        next_index = int(legacy.get("next_flow", -1))
        next_target = (
            RouteTarget.jump_workflow(workflow_ids[(group_index, next_index)])
            if 0 <= next_index < len(workflows)
            else RouteTarget.end()
        )
        loop_count = int(legacy.get("loop_count", 1))
        final_routes: list[RouteRule] = []
        if loop_count == 0:
            final_routes.append(
                RouteRule(
                    outcome=StepOutcome.SUCCESS,
                    target=RouteTarget.jump_workflow(workflow.id),
                )
            )
        else:
            if loop_count > 1:
                final_routes.append(
                    RouteRule(
                        outcome=StepOutcome.SUCCESS,
                        predicate=RoutePredicate.workflow_count(
                            workflow.id,
                            ComparisonOperator.LT,
                            loop_count,
                        ),
                        target=RouteTarget.jump_workflow(workflow.id),
                    )
                )
            final_routes.append(RouteRule(outcome=StepOutcome.SUCCESS, target=next_target))
        last = steps[-1]
        if (
            str(legacy.get("steps", [{}])[-1].get("type", "")) in {"ocr_poll", "img_poll"}
            and str(legacy.get("steps", [{}])[-1].get("on_timeout", "continue")) == "continue"
        ):
            final_routes.insert(0, RouteRule(outcome=StepOutcome.TIMEOUT, target=next_target))
        steps[-1] = last.model_copy(update={"routes": [*last.routes, *final_routes]})

        for step_index, legacy_step in enumerate(legacy.get("steps", [])):
            if str(legacy_step.get("type", "")) not in {"ocr_poll", "img_poll"}:
                continue
            if str(legacy_step.get("on_timeout", "continue")) != "continue":
                continue
            if step_index + 1 >= len(steps):
                continue
            step = steps[step_index]
            timeout_route = RouteRule(
                outcome=StepOutcome.TIMEOUT,
                target=RouteTarget.next_step(steps[step_index + 1].id),
            )
            steps[step_index] = step.model_copy(update={"routes": [*step.routes, timeout_route]})
        result.append(workflow.model_copy(update={"steps": steps}))
    return result


def _mouse_action(operation: str, position: Any, **config: Any) -> ActionSpec:
    return ActionSpec(
        capability="input.mouse",
        config={"operation": operation, "position": position, **config},
    )


def _wait_action(seconds: float) -> ActionSpec:
    return ActionSpec(capability="system.wait", config={"seconds": seconds})


def _project_asset_path(raw: Any, paths: LegacyConversionPaths) -> Path:
    filename = Path(str(raw or "")).name
    candidate = paths.project_directory / "scripts" / filename
    return _relative_or_absolute(candidate, paths.project_directory)


def _relative_or_absolute(path: Path, project_directory: Path) -> Path:
    try:
        return path.resolve().relative_to(project_directory.resolve())
    except ValueError:
        return path.resolve()


def _stable_id(value: str) -> UUID:
    return uuid5(_NAMESPACE, value)

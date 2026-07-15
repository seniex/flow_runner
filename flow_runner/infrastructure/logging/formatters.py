from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

from flow_runner.display_labels import ProjectDisplayIndex
from flow_runner.domain.enums import RunnerState, StepOutcome
from flow_runner.domain.project import Project
from flow_runner.infrastructure.logging.events import RuntimeEvent

_STATE_LABELS = {
    RunnerState.IDLE: "空闲",
    RunnerState.RUNNING: "运行中",
    RunnerState.PAUSED: "已暂停",
    RunnerState.COMPLETED: "已完成",
    RunnerState.FAILED: "失败",
    RunnerState.CANCELLED: "已取消",
}
_OUTCOME_LABELS = {
    StepOutcome.SUCCESS: "成功",
    StepOutcome.NOT_MATCHED: "未命中",
    StepOutcome.TIMEOUT: "超时",
    StepOutcome.FAILURE: "失败",
    StepOutcome.CANCELLED: "取消",
}


class RuntimeEventFormatter:
    def __init__(self, project: Project, *, debug: bool = False) -> None:
        self.debug = debug
        self._step_started: dict[tuple[UUID, UUID], float] = {}
        self.set_project(project)

    def set_project(self, project: Project) -> None:
        self._labels = ProjectDisplayIndex(project)

    def format(self, event: RuntimeEvent) -> str:
        timestamp = datetime.now().strftime("%H:%M:%S")
        location = self._location(event.workflow_id, event.step_id)
        outcome = f"：{_OUTCOME_LABELS[event.outcome]}" if event.outcome is not None else ""
        if event.kind == "runner.state":
            summary = f"任务状态：{_STATE_LABELS.get(event.state, event.state.value)}{outcome}"
        elif event.kind == "step.started":
            summary = f"开始步骤：{location}"
            if event.step_id is not None:
                self._step_started[(event.task_id, event.step_id)] = event.monotonic_timestamp
        elif event.kind == "step.finished":
            summary = f"步骤完成：{location}{outcome}"
            attempts = _condition_attempts(event.details)
            if attempts is not None:
                summary += f"，检测 {attempts} 次"
            if event.step_id is not None:
                started = self._step_started.pop((event.task_id, event.step_id), None)
                if started is not None:
                    summary += f"，耗时 {max(0.0, event.monotonic_timestamp - started):.2f} 秒"
            route = self._route_target(event.details)
            if route:
                summary += f"，路由 → {route}"
        elif event.kind == "runner.error":
            message = event.details.get("message", "未知错误")
            summary = f"运行失败：{location}，{message}"
            if event.error_id is not None:
                summary += f"（错误编号 {event.error_id}）"
        elif event.kind == "action.wait.started":
            summary = f"等待开始：{location}，共 {event.details.get('seconds', 0):g} 秒"
        elif event.kind == "action.wait.finished":
            summary = f"等待完成：{location}"
        elif event.kind == "action.wait.cancelled":
            summary = f"等待已取消：{location}"
        else:
            summary = f"运行事件：{event.kind}"
            if location:
                summary += f"，{location}"
            if outcome:
                summary += outcome
        line = f"[{timestamp}] {summary}"
        if self.debug:
            line += " | " + event.model_dump_json()
        return line

    def _location(self, workflow_id: UUID | None, step_id: UUID | None) -> str:
        if step_id is not None:
            return self._labels.step_path(step_id)
        if workflow_id is not None:
            return self._labels.workflow_path(workflow_id)
        return ""

    def _route_target(self, details: dict[str, object]) -> str:
        route = details.get("route")
        if not isinstance(route, dict):
            return ""
        target = route.get("target")
        if not isinstance(target, dict):
            return ""
        kind = target.get("kind")
        if kind == "next_step":
            step_id = _as_uuid(target.get("step_id"))
            if step_id is None:
                return "未知步骤"
            return self._labels.step_path(step_id)
        if kind in {"jump_workflow", "call_workflow"}:
            workflow_id = _as_uuid(target.get("workflow_id"))
            if workflow_id is None:
                return "未知流程"
            return self._labels.workflow_path(workflow_id)
        return {
            "return": "返回调用流程",
            "end": "结束任务",
        }.get(str(kind), str(kind or "未知目标"))


def _condition_attempts(details: dict[str, object]) -> int | None:
    result = details.get("result")
    if not isinstance(result, dict):
        return None
    value = result.get("condition_attempts")
    return value if isinstance(value, int) else None


def _as_uuid(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def route_debug_text(details: dict[str, object]) -> str:
    return json.dumps(details.get("route"), ensure_ascii=False, separators=(",", ":"))

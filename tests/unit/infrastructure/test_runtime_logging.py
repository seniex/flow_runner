import json
from datetime import datetime
from uuid import uuid4

from flow_runner.domain.enums import RunnerState, StepOutcome
from flow_runner.domain.project import AutomationStep, FlowGroup, Project, Workflow
from flow_runner.domain.routing import RouteRule, RouteTarget
from flow_runner.infrastructure.logging.events import RuntimeEvent
from flow_runner.infrastructure.logging.formatters import RuntimeEventFormatter
from flow_runner.infrastructure.logging.session import session_log_path
from flow_runner.infrastructure.logging.sinks import JsonEventSink, TextEventSink


def _event(project, workflow, step):
    return RuntimeEvent(
        task_id=uuid4(),
        kind="step.finished",
        state=RunnerState.RUNNING,
        monotonic_timestamp=1.0,
        workflow_id=workflow.id,
        step_id=step.id,
        outcome=StepOutcome.SUCCESS,
        frame_id="frame-1",
        scene_generation=7,
        details={"result": {"condition_attempts": 2}},
    )


def _project():
    step = AutomationStep(name="等待加载")
    workflow = Workflow(name="流程一", steps=[step])
    project = Project(name="项目:名称", groups=[FlowGroup(name="组A", workflows=[workflow])])
    return project, workflow, step


def test_runtime_formatter_uses_names_and_debug_adds_diagnostics():
    project, workflow, step = _project()
    event = _event(project, workflow, step)

    normal = RuntimeEventFormatter(project, debug=False).format(event)
    debug = RuntimeEventFormatter(project, debug=True).format(event)

    assert "01. 组A / 01. 流程一 / 01. 等待加载" in normal
    assert "成功" in normal
    assert str(step.id) not in normal
    assert str(step.id) in debug
    assert "frame-1" in debug
    assert '"scene_generation":7' in debug


def test_normal_formatter_reports_preserved_cancelled_condition_attempts():
    project, workflow, step = _project()
    event = RuntimeEvent(
        task_id=uuid4(),
        kind="step.finished",
        state=RunnerState.RUNNING,
        monotonic_timestamp=3.0,
        workflow_id=workflow.id,
        step_id=step.id,
        outcome=StepOutcome.CANCELLED,
        details={"result": {"condition_attempts": 3}},
    )

    line = RuntimeEventFormatter(project).format(event)

    assert "取消" in line
    assert "检测 3 次" in line


def test_session_log_path_sanitizes_reserves_and_never_overwrites(tmp_path):
    started = datetime(2026, 7, 15, 6, 15, 30)

    first = session_log_path(tmp_path, "项目:名称", started, debug=False)
    second = session_log_path(tmp_path, "项目:名称", started, debug=False)

    assert first.name == "项目_名称_20260715_061530_normal.log"
    assert second.name == "项目_名称_20260715_061530_normal_2.log"
    assert first.exists() and second.exists()


def test_session_log_path_uses_fallback_for_invalid_project_name(tmp_path):
    path = session_log_path(tmp_path, "<>: ", datetime(2026, 7, 15), debug=True)
    assert path.name == "FlowRunner_20260715_000000_debug.log"


def test_text_and_json_sinks_append_expected_mode_content(tmp_path):
    project, workflow, step = _project()
    event = _event(project, workflow, step)
    normal_path = tmp_path / "normal.log"
    debug_path = tmp_path / "debug.log"
    normal_path.touch()
    debug_path.touch()

    TextEventSink(normal_path, RuntimeEventFormatter(project)).emit(event)
    JsonEventSink(debug_path).emit(event)

    assert "01. 组A / 01. 流程一 / 01. 等待加载" in normal_path.read_text(encoding="utf-8")
    payload = json.loads(debug_path.read_text(encoding="utf-8"))
    assert payload["event_id"] == str(event.event_id)
    assert payload["details"] == event.details


def test_normal_formatter_shows_route_target_and_step_elapsed_time():
    target = AutomationStep(name="下一步")
    source = AutomationStep(name="等待加载")
    workflow = Workflow(name="流程一", steps=[source, target])
    project = Project(name="p", groups=[FlowGroup(name="组A", workflows=[workflow])])
    formatter = RuntimeEventFormatter(project)
    task_id = uuid4()
    formatter.format(
        RuntimeEvent(
            task_id=task_id,
            kind="step.started",
            state=RunnerState.RUNNING,
            monotonic_timestamp=10.0,
            workflow_id=workflow.id,
            step_id=source.id,
        )
    )
    finished = RuntimeEvent(
        task_id=task_id,
        kind="step.finished",
        state=RunnerState.RUNNING,
        monotonic_timestamp=12.5,
        workflow_id=workflow.id,
        step_id=source.id,
        outcome=StepOutcome.SUCCESS,
        details={
            "result": {"condition_attempts": 1},
            "route": RouteRule(
                outcome=StepOutcome.SUCCESS,
                target=RouteTarget.next_step(target.id),
            ).model_dump(mode="json"),
        },
    )

    line = formatter.format(finished)

    assert "耗时 2.50 秒" in line
    assert "路由 → 01. 组A / 01. 流程一 / 02. 下一步" in line

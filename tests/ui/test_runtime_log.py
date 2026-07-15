from uuid import uuid4

from PySide6.QtWidgets import QPlainTextEdit

from flow_runner.domain.enums import RunnerState
from flow_runner.domain.project import AutomationStep, FlowGroup, Project, Workflow
from flow_runner.infrastructure.logging.events import RuntimeEvent
from flow_runner.infrastructure.logging.formatters import RuntimeEventFormatter
from flow_runner.ui.runtime_log import RuntimeLogController


def test_wait_countdown_updates_one_line_and_freezes_while_paused(qtbot):
    step = AutomationStep(name="等待加载")
    workflow = Workflow(name="流程", steps=[step])
    project = Project(name="p", groups=[FlowGroup(name="组", workflows=[workflow])])
    editor = QPlainTextEdit()
    qtbot.addWidget(editor)
    now = [10.0]
    controller = RuntimeLogController(
        editor,
        RuntimeEventFormatter(project),
        clock=lambda: now[0],
    )
    task_id = uuid4()
    wait_id = str(uuid4())

    controller.consume(
        RuntimeEvent(
            task_id=task_id,
            kind="action.wait.started",
            state=RunnerState.RUNNING,
            monotonic_timestamp=10.0,
            workflow_id=workflow.id,
            step_id=step.id,
            details={"wait_id": wait_id, "seconds": 3.0, "action_index": 0},
        )
    )
    blocks = editor.blockCount()
    assert "剩余 3 秒" in editor.toPlainText()

    now[0] = 11.1
    controller.tick()
    assert editor.blockCount() == blocks
    assert "剩余 2 秒" in editor.toPlainText()

    controller.consume(_state_event(task_id, RunnerState.PAUSED, 11.1))
    now[0] = 20.0
    controller.tick()
    assert "剩余 2 秒" in editor.toPlainText()

    controller.consume(_state_event(task_id, RunnerState.RUNNING, 20.0))
    now[0] = 21.1
    controller.tick()
    assert "剩余 1 秒" in editor.toPlainText()

    controller.consume(
        RuntimeEvent(
            task_id=task_id,
            kind="action.wait.finished",
            state=RunnerState.RUNNING,
            monotonic_timestamp=21.1,
            workflow_id=workflow.id,
            step_id=step.id,
            details={"wait_id": wait_id, "seconds": 3.0, "action_index": 0},
        )
    )
    assert editor.blockCount() == blocks + 2  # pause and resume are ordinary log rows
    assert "等待完成" in editor.toPlainText()


def _state_event(task_id, state, timestamp):
    return RuntimeEvent(
        task_id=task_id,
        kind="runner.state",
        state=state,
        monotonic_timestamp=timestamp,
    )

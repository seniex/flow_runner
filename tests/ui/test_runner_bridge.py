import base64
from time import monotonic
from uuid import uuid4

from PySide6.QtCore import QThread
from PySide6.QtGui import QPixmap

from flow_runner.domain.enums import RunnerState, StepOutcome
from flow_runner.domain.project import AutomationStep, FlowGroup, Project, Workflow
from flow_runner.domain.results import StepResult
from flow_runner.engine.runner import Runner
from flow_runner.infrastructure.logging.events import RuntimeEvent
from flow_runner.infrastructure.logging.sinks import JsonLinesEventSink
from flow_runner.ui.dialogs.diagnostics_dialog import DiagnosticsDialog
from flow_runner.ui.runner_bridge import RunnerBridge
from flow_runner.ui.view_models.run_view_model import RunViewModel


class ImmediateExecutor:
    async def execute(self, step):
        return StepResult(outcome=StepOutcome.SUCCESS)


def test_runner_bridge_delivers_events_and_completion_on_qt_thread(qtbot):
    workflow = Workflow(name="main", steps=[AutomationStep(name="step")])
    project = Project(name="p", groups=[FlowGroup(name="g", workflows=[workflow])])
    runner = Runner(ImmediateExecutor())
    bridge = RunnerBridge(runner)
    received_threads = []
    events = []

    def on_event(event):
        received_threads.append(QThread.currentThread())
        events.append(event)

    bridge.eventReceived.connect(on_event)
    with qtbot.waitSignal(bridge.finished, timeout=3000) as blocker:
        bridge.start(project, workflow.id)

    assert blocker.args[0].terminal_outcome is StepOutcome.SUCCESS
    assert [event.kind for event in events] == [
        "runner.state",
        "step.started",
        "step.finished",
        "runner.state",
    ]
    assert all(thread is bridge.thread() for thread in received_threads)


def test_runner_bridge_fans_out_events_to_persistent_log(qtbot, tmp_path):
    workflow = Workflow(name="main", steps=[AutomationStep(name="step")])
    project = Project(name="p", groups=[FlowGroup(name="g", workflows=[workflow])])
    log_path = tmp_path / "logs" / "runtime.jsonl"
    bridge = RunnerBridge(
        Runner(ImmediateExecutor()),
        persistent_event_sink=JsonLinesEventSink(log_path),
    )

    with qtbot.waitSignal(bridge.finished, timeout=3000):
        bridge.start(project, workflow.id)

    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 4
    assert '"kind":"step.finished"' in lines[2]


def test_runner_bridge_reports_persistent_sink_failure_without_stopping_run(qtbot):
    class BrokenSink:
        def emit(self, _event):
            raise OSError("disk full")

    workflow = Workflow(name="main", steps=[AutomationStep(name="step")])
    project = Project(name="p", groups=[FlowGroup(name="g", workflows=[workflow])])
    bridge = RunnerBridge(Runner(ImmediateExecutor()), persistent_event_sink=BrokenSink())
    failures = []
    bridge.failed.connect(failures.append)

    with qtbot.waitSignal(bridge.finished, timeout=3000):
        bridge.start(project, workflow.id)

    assert any("日志写入失败" in message and "disk full" in message for message in failures)


def test_runner_bridge_rejects_parallel_start(qtbot):
    workflow = Workflow(name="main", steps=[])
    project = Project(name="p", groups=[FlowGroup(name="g", workflows=[workflow])])
    bridge = RunnerBridge(Runner(ImmediateExecutor()))
    bridge._running = True

    with qtbot.waitSignal(bridge.failed, timeout=1000) as blocker:
        bridge.start(project, workflow.id)

    assert "already running" in blocker.args[0]


def test_runner_bridge_shutdown_cancels_and_joins_runtime_thread(qtbot):
    workflow = Workflow(name="main", steps=[AutomationStep(name="wait")])
    project = Project(name="p", groups=[FlowGroup(name="g", workflows=[workflow])])

    class WaitingExecutor:
        def __init__(self, token):
            self.token = token

        async def execute(self, step):
            await self.token.sleep(60)
            return StepResult(outcome=StepOutcome.SUCCESS)

    bridge = RunnerBridge(Runner(step_executor_factory=WaitingExecutor))
    with qtbot.waitSignal(bridge.eventReceived, timeout=3000):
        bridge.start(project, workflow.id)

    bridge.shutdown(timeout_seconds=3.0)

    assert not bridge.is_running


def test_diagnostics_dialog_displays_structured_event(qtbot):
    dialog = DiagnosticsDialog()
    qtbot.addWidget(dialog)
    task_id = uuid4()
    workflow_id = uuid4()
    step_id = uuid4()
    event = RuntimeEvent(
        task_id=task_id,
        kind="step.finished",
        state=RunnerState.RUNNING,
        monotonic_timestamp=monotonic(),
        workflow_id=workflow_id,
        step_id=step_id,
        outcome=StepOutcome.SUCCESS,
        frame_id="frame-1",
        scene_generation=4,
        details={"retry": 2},
    )

    dialog.update_event(event)

    assert dialog.state_value.text() == "运行中"
    assert dialog.kind_value.text() == "步骤完成"
    assert dialog.task_value.text() == str(task_id)
    assert dialog.workflow_value.text() == str(workflow_id)
    assert dialog.step_value.text() == str(step_id)
    assert dialog.outcome_value.text() == "成功"
    assert dialog.frame_value.text() == "frame-1"
    assert dialog.scene_value.text() == "4"
    assert "retry" in dialog.details_value.toPlainText()


def test_diagnostics_dialog_previews_optional_capture(qtbot, tmp_path):
    capture_path = tmp_path / "capture.png"
    pixmap = QPixmap(4, 3)
    assert pixmap.save(str(capture_path))
    dialog = DiagnosticsDialog()
    qtbot.addWidget(dialog)
    event = RuntimeEvent(
        task_id=uuid4(),
        kind="condition.preview",
        state=RunnerState.RUNNING,
        monotonic_timestamp=monotonic(),
        diagnostic_capture_path=str(capture_path),
    )

    dialog.update_event(event)

    preview = dialog.capture_value.pixmap()
    assert preview is not None
    assert not preview.isNull()
    assert preview.size().width() == 4
    assert preview.size().height() == 3


def test_diagnostics_dialog_previews_in_memory_capture(qtbot, tmp_path):
    capture_path = tmp_path / "capture.png"
    source = QPixmap(6, 2)
    assert source.save(str(capture_path))
    dialog = DiagnosticsDialog()
    qtbot.addWidget(dialog)
    event = RuntimeEvent(
        task_id=uuid4(),
        kind="condition.preview",
        state=RunnerState.RUNNING,
        monotonic_timestamp=monotonic(),
        diagnostic_capture_base64=base64.b64encode(capture_path.read_bytes()).decode("ascii"),
    )

    dialog.update_event(event)

    preview = dialog.capture_value.pixmap()
    assert preview is not None
    assert preview.size().width() == 6
    assert preview.size().height() == 2


def test_run_view_model_tracks_latest_runtime_event(qtbot):
    model = RunViewModel()
    event = RuntimeEvent(
        task_id=uuid4(),
        kind="runner.state",
        state=RunnerState.PAUSED,
        monotonic_timestamp=monotonic(),
    )
    with qtbot.waitSignal(model.stateChanged):
        model.consume(event)
    assert model.state is RunnerState.PAUSED

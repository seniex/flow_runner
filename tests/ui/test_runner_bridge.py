from time import monotonic
from uuid import uuid4

from PySide6.QtCore import QThread

from flow_runner.domain.enums import RunnerState, StepOutcome
from flow_runner.domain.project import AutomationStep, FlowGroup, Project, Workflow
from flow_runner.domain.results import StepResult
from flow_runner.engine.runner import Runner
from flow_runner.infrastructure.logging.events import RuntimeEvent
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
    assert [event.state for event in events] == [
        RunnerState.RUNNING,
        RunnerState.COMPLETED,
    ]
    assert all(thread is bridge.thread() for thread in received_threads)


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
    event = RuntimeEvent(
        task_id=uuid4(),
        kind="runner.state",
        state=RunnerState.RUNNING,
        monotonic_timestamp=monotonic(),
        frame_id="frame-1",
        details={"retry": 2},
    )

    dialog.update_event(event)

    assert dialog.state_value.text() == "running"
    assert dialog.frame_value.text() == "frame-1"
    assert "retry" in dialog.details_value.toPlainText()


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

from __future__ import annotations

import asyncio
import threading
from uuid import UUID

from PySide6.QtCore import QObject, Signal

from flow_runner.domain.project import Project
from flow_runner.engine.runner import Runner
from flow_runner.engine.workflow_executor import WorkflowTrace
from flow_runner.infrastructure.logging.events import RuntimeEvent
from flow_runner.infrastructure.logging.sinks import EventSink


class _SignalEventSink(EventSink):
    def __init__(self, bridge: RunnerBridge) -> None:
        self.bridge = bridge

    def emit(self, event: RuntimeEvent) -> None:
        self.bridge.eventReceived.emit(event)


class RunnerBridge(QObject):
    eventReceived = Signal(object)
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, runner: Runner) -> None:
        super().__init__()
        self.runner = runner
        self.runner.event_sink = _SignalEventSink(self)
        self._running = False
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self, project: Project, entry_workflow_id: UUID) -> None:
        if self._running:
            self.failed.emit("runner is already running")
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run,
            args=(project, entry_workflow_id),
            daemon=True,
            name="FlowRunnerRuntime",
        )
        self._thread.start()

    def stop(self) -> None:
        loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(self.runner.stop)

    def _run(self, project: Project, entry_workflow_id: UUID) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            trace: WorkflowTrace = loop.run_until_complete(
                self.runner.start(project, entry_workflow_id)
            )
        except Exception as error:
            self.failed.emit(str(error))
        else:
            self.finished.emit(trace)
        finally:
            self._running = False
            self._loop = None
            loop.close()

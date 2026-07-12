from __future__ import annotations

import asyncio
import queue
import threading
from uuid import UUID

from PySide6.QtCore import QMetaObject, QObject, Qt, Signal, Slot

from flow_runner.domain.project import Project
from flow_runner.engine.runner import Runner
from flow_runner.engine.workflow_executor import WorkflowTrace
from flow_runner.infrastructure.logging.events import RuntimeEvent
from flow_runner.infrastructure.logging.sinks import EventSink


class _SignalEventSink(EventSink):
    def __init__(self, bridge: RunnerBridge) -> None:
        self.bridge = bridge

    def emit(self, event: RuntimeEvent) -> None:
        self.bridge._post("event", event)


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
        self._messages: queue.SimpleQueue[tuple[str, object]] = queue.SimpleQueue()

    def start(self, project: Project, entry_workflow_id: UUID) -> None:
        if self._running:
            self._post("failed", "runner is already running")
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

    def pause(self) -> None:
        loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(self.runner.pause)

    def resume(self) -> None:
        loop = self._loop
        if loop is not None:
            loop.call_soon_threadsafe(self.runner.resume)

    @property
    def is_running(self) -> bool:
        return self._running

    def shutdown(self, *, timeout_seconds: float = 5.0) -> None:
        self.stop()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout_seconds)
        if thread is not None and thread.is_alive():
            self._post("failed", "runner did not stop before shutdown timeout")
        self._drain_messages()

    def _run(self, project: Project, entry_workflow_id: UUID) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            trace: WorkflowTrace = loop.run_until_complete(
                self.runner.start(project, entry_workflow_id)
            )
        except Exception as error:
            self._post("failed", str(error))
        else:
            self._post("finished", trace)
        finally:
            self._running = False
            self._loop = None
            self._thread = None
            loop.close()

    def _post(self, kind: str, payload: object) -> None:
        self._messages.put((kind, payload))
        try:
            QMetaObject.invokeMethod(
                self,
                "_drain_messages",
                Qt.ConnectionType.QueuedConnection,
            )
        except RuntimeError:
            pass

    @Slot()
    def _drain_messages(self) -> None:
        while True:
            try:
                kind, payload = self._messages.get_nowait()
            except queue.Empty:
                return
            if kind == "event":
                self.eventReceived.emit(payload)
            elif kind == "finished":
                self.finished.emit(payload)
            else:
                self.failed.emit(str(payload))

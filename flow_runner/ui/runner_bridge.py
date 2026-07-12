from __future__ import annotations

import asyncio
import queue
import threading
from collections.abc import Coroutine
from typing import Any
from uuid import UUID

from PySide6.QtCore import QMetaObject, QObject, Qt, Signal, Slot

from flow_runner.domain.project import Project
from flow_runner.engine.runner import Runner
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
    terminated = Signal()

    def __init__(self, runner: Runner) -> None:
        super().__init__()
        self.runner = runner
        self.runner.event_sink = _SignalEventSink(self)
        self._running = False
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._messages: queue.SimpleQueue[tuple[str, object]] = queue.SimpleQueue()

    def start(self, project: Project, entry_workflow_id: UUID) -> None:
        self._start_thread("workflow", project, entry_workflow_id)

    def start_parallel(self, project: Project, block_id: UUID) -> None:
        self._start_thread("parallel", project, block_id)

    def run_step(self, project: Project, workflow_id: UUID, step_id: UUID) -> None:
        self._start_thread("step", project, workflow_id, step_id)

    def preview_condition(self, project: Project, workflow_id: UUID, step_id: UUID) -> None:
        self._start_thread("preview", project, workflow_id, step_id)

    def _start_thread(
        self,
        mode: str,
        project: Project,
        entry_id: UUID,
        step_id: UUID | None = None,
    ) -> None:
        if self._running:
            self._post("failed", "runner is already running")
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._run,
            args=(mode, project, entry_id, step_id),
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

    def _run(
        self,
        mode: str,
        project: Project,
        entry_id: UUID,
        step_id: UUID | None,
    ) -> None:
        loop = asyncio.new_event_loop()
        self._loop = loop
        asyncio.set_event_loop(loop)
        try:
            if mode in {"step", "preview"} and step_id is None:
                raise ValueError(f"{mode} mode requires a step id")
            operation: Coroutine[Any, Any, object]
            if mode == "parallel":
                operation = self.runner.start_parallel(project, entry_id)
            elif mode == "step":
                assert step_id is not None
                operation = self.runner.run_step(project, entry_id, step_id)
            elif mode == "preview":
                assert step_id is not None
                operation = self.runner.preview_condition(project, entry_id, step_id)
            else:
                operation = self.runner.start(project, entry_id)
            trace = loop.run_until_complete(operation)
        except Exception as error:
            self._post("failed", str(error))
        else:
            self._post("finished", trace)
        finally:
            self._running = False
            self._loop = None
            self._thread = None
            loop.close()
            self._post("terminated", object())

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
            elif kind == "terminated":
                self.terminated.emit()
            else:
                self.failed.emit(str(payload))

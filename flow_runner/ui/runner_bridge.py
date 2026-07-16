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
from flow_runner.infrastructure.logging.sinks import CompositeEventSink, EventSink


class _SignalEventSink(EventSink):
    def __init__(self, bridge: RunnerBridge) -> None:
        self.bridge = bridge

    def emit(self, event: RuntimeEvent) -> None:
        self.bridge._post("event", event)


class _SafeEventSink(EventSink):
    def __init__(self, bridge: RunnerBridge, delegate: EventSink) -> None:
        self.bridge = bridge
        self.delegate = delegate

    def emit(self, event: RuntimeEvent) -> None:
        try:
            self.delegate.emit(event)
        except Exception as error:
            self.bridge._post("failed", f"日志写入失败：{error}")


class RunnerBridge(QObject):
    eventReceived = Signal(object)
    finished = Signal(object)
    failed = Signal(str)
    terminated = Signal()

    def __init__(self, runner: Runner, *, persistent_event_sink: EventSink | None = None) -> None:
        super().__init__()
        self.runner = runner
        signal_sink = _SignalEventSink(self)
        self.runner.event_sink = (
            CompositeEventSink(signal_sink, _SafeEventSink(self, persistent_event_sink))
            if persistent_event_sink is not None
            else signal_sink
        )
        self._running = False
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._messages: queue.SimpleQueue[tuple[str, object]] = queue.SimpleQueue()

    def start(self, project: Project, entry_workflow_id: UUID) -> bool:
        return self._start_thread("workflow", project, entry_workflow_id)

    def start_parallel(self, project: Project, block_id: UUID) -> bool:
        return self._start_thread("parallel", project, block_id)

    def run_step(self, project: Project, workflow_id: UUID, step_id: UUID) -> bool:
        return self._start_thread("step", project, workflow_id, step_id)

    def preview_condition(self, project: Project, workflow_id: UUID, step_id: UUID) -> bool:
        return self._start_thread("preview", project, workflow_id, step_id)

    def _start_thread(
        self,
        mode: str,
        project: Project,
        entry_id: UUID,
        step_id: UUID | None = None,
    ) -> bool:
        if self._running:
            self._post("failed", "runner is already running")
            return False
        self._running = True
        self._thread = threading.Thread(
            target=self._run,
            args=(mode, project, entry_id, step_id),
            daemon=True,
            name="FlowRunnerRuntime",
        )
        self._thread.start()
        return True

    def stop(self) -> bool:
        loop = self._loop
        if loop is None:
            return False
        loop.call_soon_threadsafe(self.runner.stop)
        return True

    def pause(self) -> bool:
        loop = self._loop
        if loop is None:
            return False
        loop.call_soon_threadsafe(self.runner.pause)
        return True

    def resume(self) -> bool:
        loop = self._loop
        if loop is None:
            return False
        loop.call_soon_threadsafe(self.runner.resume)
        return True

    @property
    def is_running(self) -> bool:
        return self._running

    def shutdown(self, *, timeout_seconds: float = 5.0) -> bool:
        self.stop()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout_seconds)
        stopped = thread is None or not thread.is_alive()
        if not stopped:
            self._post("failed", "runner did not stop before shutdown timeout")
        self._drain_messages()
        return stopped

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

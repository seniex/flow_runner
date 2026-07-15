from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from uuid import UUID

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QTextBlock, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit

from flow_runner.domain.enums import RunnerState
from flow_runner.infrastructure.logging.events import RuntimeEvent
from flow_runner.infrastructure.logging.formatters import RuntimeEventFormatter


@dataclass
class _ActiveWait:
    event: RuntimeEvent
    block: QTextBlock
    total_seconds: float
    elapsed_seconds: float
    running_since: float | None


class RuntimeLogController(QObject):
    def __init__(
        self,
        editor: QPlainTextEdit,
        formatter: RuntimeEventFormatter,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        super().__init__(editor)
        self.editor = editor
        self.formatter = formatter
        self.clock = clock
        self._active: dict[tuple[UUID, str], _ActiveWait] = {}
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)
        self.editor.document().setMaximumBlockCount(2000)

    def consume(self, event: RuntimeEvent) -> None:
        if event.kind == "action.wait.started":
            self._start_wait(event)
            return
        if event.kind in {"action.wait.finished", "action.wait.cancelled"}:
            if self._finish_wait(event):
                return
        if event.kind == "runner.state":
            self._apply_state(event)
        self._append(self.formatter.format(event))

    def tick(self) -> None:
        now = self.clock()
        for active in self._active.values():
            elapsed = active.elapsed_seconds
            if active.running_since is not None:
                elapsed += max(0.0, now - active.running_since)
            remaining = max(0, math.ceil(active.total_seconds - elapsed))
            self._replace_block(active.block, self._countdown_line(active.event, remaining))

    def _start_wait(self, event: RuntimeEvent) -> None:
        wait_id = str(event.details.get("wait_id", ""))
        seconds = float(event.details.get("seconds", 0.0))
        self._append(self._countdown_line(event, math.ceil(seconds)))
        key = (event.task_id, wait_id)
        self._active[key] = _ActiveWait(
            event=event,
            block=self.editor.document().lastBlock(),
            total_seconds=seconds,
            elapsed_seconds=0.0,
            running_since=self.clock(),
        )
        if not self.timer.isActive():
            self.timer.start()

    def _finish_wait(self, event: RuntimeEvent) -> bool:
        key = (event.task_id, str(event.details.get("wait_id", "")))
        active = self._active.pop(key, None)
        if active is None:
            return False
        self._replace_block(active.block, self.formatter.format(event))
        if not self._active:
            self.timer.stop()
        return True

    def _apply_state(self, event: RuntimeEvent) -> None:
        now = self.clock()
        matching = [
            active
            for (task_id, _wait_id), active in self._active.items()
            if task_id == event.task_id
        ]
        if event.state is RunnerState.PAUSED:
            for active in matching:
                if active.running_since is not None:
                    active.elapsed_seconds += max(0.0, now - active.running_since)
                    active.running_since = None
        elif event.state is RunnerState.RUNNING:
            for active in matching:
                if active.running_since is None:
                    active.running_since = now
        elif event.state in {
            RunnerState.COMPLETED,
            RunnerState.FAILED,
            RunnerState.CANCELLED,
        }:
            for key, active in list(self._active.items()):
                if key[0] == event.task_id:
                    self._replace_block(
                        active.block,
                        self.formatter.format(
                            active.event.model_copy(
                                update={"kind": "action.wait.cancelled", "state": event.state}
                            )
                        ),
                    )
                    del self._active[key]
            if not self._active:
                self.timer.stop()

    def _countdown_line(self, event: RuntimeEvent, remaining: int) -> str:
        line = self.formatter.format(event)
        line = line.replace("等待开始：", "等待中：", 1)
        marker = "，共 "
        if marker in line:
            prefix, suffix = line.split(marker, 1)
            debug = f" | {suffix.split(' | ', 1)[1]}" if " | " in suffix else ""
            return f"{prefix}，剩余 {remaining} 秒{debug}"
        return f"{line}，剩余 {remaining} 秒"

    def _append(self, text: str) -> None:
        self.editor.appendPlainText(text)
        self.editor.verticalScrollBar().setValue(self.editor.verticalScrollBar().maximum())

    @staticmethod
    def _replace_block(block: QTextBlock, text: str) -> None:
        if not block.isValid():
            return
        cursor = QTextCursor(block)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(
            QTextCursor.MoveOperation.EndOfBlock,
            QTextCursor.MoveMode.KeepAnchor,
        )
        cursor.insertText(text)

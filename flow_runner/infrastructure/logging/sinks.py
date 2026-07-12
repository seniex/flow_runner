from __future__ import annotations

from pathlib import Path
from typing import Protocol

from flow_runner.infrastructure.logging.events import RuntimeEvent


class EventSink(Protocol):
    def emit(self, event: RuntimeEvent) -> None: ...


class NullEventSink:
    def emit(self, event: RuntimeEvent) -> None:
        del event


class MemoryEventSink:
    def __init__(self) -> None:
        self.events: list[RuntimeEvent] = []

    def emit(self, event: RuntimeEvent) -> None:
        self.events.append(event)


class JsonLinesEventSink:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def emit(self, event: RuntimeEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(event.model_dump_json())
            stream.write("\n")
            stream.flush()

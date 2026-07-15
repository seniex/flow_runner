from __future__ import annotations

from pathlib import Path
from typing import Protocol

from flow_runner.infrastructure.logging.events import RuntimeEvent
from flow_runner.infrastructure.logging.formatters import RuntimeEventFormatter


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


class CompositeEventSink:
    def __init__(self, *sinks: EventSink) -> None:
        self.sinks = sinks

    def emit(self, event: RuntimeEvent) -> None:
        for sink in self.sinks:
            sink.emit(event)


class JsonLinesEventSink:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def emit(self, event: RuntimeEvent) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(event.model_dump_json())
            stream.write("\n")
            stream.flush()


class TextEventSink:
    def __init__(self, path: str | Path, formatter: RuntimeEventFormatter) -> None:
        self.path = Path(path)
        self.formatter = formatter

    def emit(self, event: RuntimeEvent) -> None:
        _append_line(self.path, self.formatter.format(event))


class JsonEventSink:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def emit(self, event: RuntimeEvent) -> None:
        _append_line(self.path, event.model_dump_json())


def _append_line(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
        stream.write("\n")
        stream.flush()

import asyncio
import importlib
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter


class RecordedEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    timestamp: float = Field(ge=0)
    kind: str = Field(min_length=1)
    data: dict[str, Any] = Field(default_factory=dict)


class RecordingStore:
    _adapter = TypeAdapter(list[RecordedEvent])

    @classmethod
    def save(cls, path: Path, events: list[RecordedEvent]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(cls._adapter.dump_json(events, indent=2).decode(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> list[RecordedEvent]:
        return cls._adapter.validate_json(path.read_text(encoding="utf-8"))


class RecordingPlayer:
    def __init__(
        self,
        *,
        sleep: Callable[[float], Awaitable[None]],
        backend: Any | None = None,
    ) -> None:
        self.sleep = sleep
        self.backend = backend or importlib.import_module("pyautogui")

    async def __call__(self, path: Path, speed: float, max_gap: float) -> None:
        events = RecordingStore.load(path)
        previous = 0.0
        for event in events:
            delay = min(max(0.0, event.timestamp - previous) / speed, max_gap)
            await self.sleep(delay)
            await asyncio.to_thread(self._dispatch, event)
            previous = event.timestamp

    def _dispatch(self, event: RecordedEvent) -> None:
        data = event.data
        if event.kind == "move":
            self.backend.moveTo(int(data["x"]), int(data["y"]))
        elif event.kind == "click":
            self.backend.click(
                x=int(data["x"]),
                y=int(data["y"]),
                button=str(data.get("button", "left")),
            )
        elif event.kind == "scroll":
            self.backend.moveTo(int(data["x"]), int(data["y"]))
            self.backend.scroll(int(data["units"]))
        elif event.kind == "key_press":
            self.backend.keyDown(str(data["key"]))
        elif event.kind == "key_release":
            self.backend.keyUp(str(data["key"]))
        else:
            raise ValueError(f"unknown recorded event kind: {event.kind}")

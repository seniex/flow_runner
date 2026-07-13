import asyncio
import importlib
import random
import threading
from collections.abc import Awaitable, Callable
from pathlib import Path
from time import monotonic
from typing import Any, Protocol

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


class RecordingListener(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...


class RecordingListenerFactory(Protocol):
    def __call__(
        self,
        *,
        on_move: Callable[[int, int], None],
        on_click: Callable[[int, int, object, bool], None],
        on_scroll: Callable[[int, int, int, int], None],
        on_press: Callable[[object], None],
        on_release: Callable[[object], None],
    ) -> RecordingListener: ...


class RecordingRecorder:
    def __init__(
        self,
        *,
        listener_factory: RecordingListenerFactory | None = None,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.listener_factory = listener_factory or _pynput_recording_listener
        self.clock = clock
        self.listener: RecordingListener | None = None
        self.started_at = 0.0
        self.events: list[RecordedEvent] = []
        self._lock = threading.Lock()

    @property
    def is_recording(self) -> bool:
        return self.listener is not None

    def start(self) -> None:
        if self.listener is not None:
            return
        with self._lock:
            self.events = []
            self.started_at = self.clock()
        self.listener = self.listener_factory(
            on_move=self._on_move,
            on_click=self._on_click,
            on_scroll=self._on_scroll,
            on_press=self._on_press,
            on_release=self._on_release,
        )
        self.listener.start()

    def stop(self, path: Path) -> list[RecordedEvent]:
        listener = self.listener
        if listener is None:
            return []
        listener.stop()
        self.listener = None
        with self._lock:
            events = list(self.events)
        path.parent.mkdir(parents=True, exist_ok=True)
        RecordingStore.save(path, events)
        return events

    def _append(self, kind: str, data: dict[str, Any]) -> None:
        with self._lock:
            self.events.append(
                RecordedEvent(
                    timestamp=max(0.0, self.clock() - self.started_at),
                    kind=kind,
                    data=data,
                )
            )

    def _on_move(self, x: int, y: int) -> None:
        self._append("move", {"x": x, "y": y})

    def _on_click(self, x: int, y: int, button: object, pressed: bool) -> None:
        if pressed:
            self._append("click", {"x": x, "y": y, "button": _input_name(button)})

    def _on_scroll(self, x: int, y: int, dx: int, dy: int) -> None:
        del dx
        self._append("scroll", {"x": x, "y": y, "units": dy})

    def _on_press(self, key: object) -> None:
        self._append("key_press", {"key": _input_name(key)})

    def _on_release(self, key: object) -> None:
        self._append("key_release", {"key": _input_name(key)})


class RecordingPlayer:
    def __init__(
        self,
        *,
        sleep: Callable[[float], Awaitable[None]],
        backend: Any | None = None,
        uniform: Callable[[float, float], float] = random.uniform,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self.sleep = sleep
        self.backend = backend or importlib.import_module("pyautogui")
        self.uniform = uniform
        self.clock = clock
        self._held_keys: set[str] = set()

    async def __call__(
        self,
        path: Path,
        speed: float,
        max_gap: float,
        jitter_ms: int = 0,
    ) -> None:
        events = RecordingStore.load(path)
        previous = 0.0
        scheduled = 0.0
        started_at = self.clock()
        self._held_keys.clear()
        missing = object()
        original_pause = getattr(self.backend, "PAUSE", missing)
        if original_pause is not missing:
            _set_backend_pause(self.backend, 0)
        try:
            for event in events:
                gap = max(0.0, event.timestamp - previous) / speed
                scheduled += min(gap, max_gap) if max_gap > 0 else gap
                target = scheduled
                if jitter_ms:
                    jitter_seconds = jitter_ms / 1000
                    target = max(
                        0.0,
                        target + self.uniform(-jitter_seconds, jitter_seconds),
                    )
                delay = max(0.0, target - (self.clock() - started_at))
                await self.sleep(delay)
                await asyncio.to_thread(self._dispatch, event)
                previous = event.timestamp
        finally:
            try:
                await asyncio.to_thread(self._release_held_keys)
            finally:
                if original_pause is not missing:
                    _set_backend_pause(self.backend, original_pause)

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
            key = str(data["key"])
            self.backend.keyDown(key)
            self._held_keys.add(key)
        elif event.kind == "key_release":
            key = str(data["key"])
            self.backend.keyUp(key)
            self._held_keys.discard(key)
        else:
            raise ValueError(f"unknown recorded event kind: {event.kind}")

    def _release_held_keys(self) -> None:
        keys = tuple(self._held_keys)
        self._held_keys.clear()
        for key in keys:
            try:
                self.backend.keyUp(key)
            except Exception:
                continue


class _CompositeListener:
    def __init__(self, listeners: list[Any]) -> None:
        self.listeners = listeners

    def start(self) -> None:
        for listener in self.listeners:
            listener.start()

    def stop(self) -> None:
        for listener in self.listeners:
            listener.stop()


def _pynput_recording_listener(
    *,
    on_move: Callable[[int, int], None],
    on_click: Callable[[int, int, object, bool], None],
    on_scroll: Callable[[int, int, int, int], None],
    on_press: Callable[[object], None],
    on_release: Callable[[object], None],
) -> RecordingListener:
    mouse = importlib.import_module("pynput.mouse")
    keyboard = importlib.import_module("pynput.keyboard")
    return _CompositeListener(
        [
            mouse.Listener(on_move=on_move, on_click=on_click, on_scroll=on_scroll),
            keyboard.Listener(on_press=on_press, on_release=on_release),
        ]
    )


def _input_name(value: object) -> str:
    char = getattr(value, "char", None)
    if char:
        return str(char)
    name = getattr(value, "name", None)
    if name:
        return str(name)
    return str(value).rsplit(".", 1)[-1]


def _set_backend_pause(backend: Any, value: Any) -> None:
    backend.PAUSE = value

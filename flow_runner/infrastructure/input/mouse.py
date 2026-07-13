import asyncio
import importlib
import inspect
import math
import threading
from collections.abc import Awaitable, Callable
from time import monotonic
from typing import Any, Protocol


class MouseDevice(Protocol):
    async def click(self, **kwargs: object) -> None: ...
    async def move(self, **kwargs: object) -> None: ...
    async def scroll(self, **kwargs: object) -> None: ...
    async def button_down(self, **kwargs: object) -> None: ...
    async def button_up(self, **kwargs: object) -> None: ...
    async def drag(self, **kwargs: object) -> None: ...
    def release_all(self) -> None: ...


class PyAutoGuiMouseDevice:
    _segment_seconds = 1 / 60

    def __init__(
        self,
        backend: Any | None = None,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        if backend is None:
            backend = importlib.import_module("pyautogui")
        self.backend = backend
        try:
            move_to = self.backend.moveTo
            self._move_supports_pause = "_pause" in inspect.signature(move_to).parameters
        except (AttributeError, TypeError, ValueError):
            self._move_supports_pause = False
        self.sleep = sleep
        self.clock = clock
        self._held_buttons: set[str] = set()
        self._state_lock = threading.Lock()

    async def click(self, **kwargs: object) -> None:
        position = kwargs["position"]
        if not isinstance(position, tuple):
            raise TypeError("mouse position must be a tuple")
        clicks = _integer(kwargs, "clicks")
        interval = _number(kwargs, "interval")
        for index in range(clicks):
            await asyncio.to_thread(
                self.backend.click,
                x=position[0],
                y=position[1],
                button=kwargs["button"],
                clicks=1,
                interval=0.0,
            )
            if interval > 0 and index + 1 < clicks:
                await asyncio.sleep(interval)

    async def move(self, **kwargs: object) -> None:
        position = kwargs["position"]
        if not isinstance(position, tuple):
            raise TypeError("mouse position must be a tuple")
        await self._move_to(position, _number(kwargs, "duration"))

    async def scroll(self, **kwargs: object) -> None:
        position = kwargs["position"]
        if not isinstance(position, tuple):
            raise TypeError("mouse position must be a tuple")
        await asyncio.to_thread(self.backend.moveTo, position[0], position[1])
        await asyncio.to_thread(self.backend.scroll, kwargs["units"])

    async def button_down(self, **kwargs: object) -> None:
        position = _position(kwargs)
        await asyncio.to_thread(self._button_down, position, str(kwargs["button"]))

    async def button_up(self, **kwargs: object) -> None:
        position = _position(kwargs)
        await asyncio.to_thread(self._button_up, position, str(kwargs["button"]))

    async def drag(self, **kwargs: object) -> None:
        position = _position(kwargs)
        button = str(kwargs["button"])
        await asyncio.to_thread(self._button_down_current, button)
        try:
            await self._move_to(position, _number(kwargs, "duration"))
        finally:
            await asyncio.to_thread(self._button_up_current, button)

    def release_all(self) -> None:
        with self._state_lock:
            buttons = tuple(self._held_buttons)
            self._held_buttons.clear()
            for button in buttons:
                try:
                    self.backend.mouseUp(button=button)
                except Exception:
                    continue

    def _button_down(self, position: tuple[int, int], button: str) -> None:
        with self._state_lock:
            self.backend.mouseDown(x=position[0], y=position[1], button=button)
            self._held_buttons.add(button)

    def _button_up(self, position: tuple[int, int], button: str) -> None:
        with self._state_lock:
            self.backend.mouseUp(x=position[0], y=position[1], button=button)
            self._held_buttons.discard(button)

    def _button_down_current(self, button: str) -> None:
        with self._state_lock:
            self.backend.mouseDown(button=button)
            self._held_buttons.add(button)

    def _button_up_current(self, button: str) -> None:
        with self._state_lock:
            self.backend.mouseUp(button=button)
            self._held_buttons.discard(button)

    async def _move_to(self, position: tuple[int, int], duration: float) -> None:
        if duration <= 0:
            await asyncio.to_thread(self._move_immediate, position[0], position[1])
            return
        start = await asyncio.to_thread(self.backend.position)
        start_x, start_y = int(start[0]), int(start[1])
        steps = max(1, math.ceil(duration / self._segment_seconds))
        started_at = self.clock()
        for index in range(1, steps + 1):
            target = started_at + duration * index / steps
            await self.sleep(max(0.0, target - self.clock()))
            ratio = index / steps
            x = round(start_x + (position[0] - start_x) * ratio)
            y = round(start_y + (position[1] - start_y) * ratio)
            await asyncio.to_thread(self._move_immediate, x, y)

    def _move_immediate(self, x: int, y: int) -> None:
        if self._move_supports_pause:
            self.backend.moveTo(x, y, _pause=False)
        else:
            self.backend.moveTo(x, y)


def _position(kwargs: dict[str, object]) -> tuple[int, int]:
    position = kwargs["position"]
    if not isinstance(position, tuple):
        raise TypeError("mouse position must be a tuple")
    return position


def _integer(kwargs: dict[str, object], name: str) -> int:
    value = kwargs[name]
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"mouse {name} must be an integer")
    return value


def _number(kwargs: dict[str, object], name: str) -> float:
    value = kwargs[name]
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise TypeError(f"mouse {name} must be numeric")
    return float(value)

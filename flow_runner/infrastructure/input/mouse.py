import asyncio
import importlib
import threading
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
    def __init__(self, backend: Any | None = None) -> None:
        if backend is None:
            backend = importlib.import_module("pyautogui")
        self.backend = backend
        self._held_buttons: set[str] = set()
        self._state_lock = threading.Lock()

    async def click(self, **kwargs: object) -> None:
        position = kwargs["position"]
        if not isinstance(position, tuple):
            raise TypeError("mouse position must be a tuple")
        await asyncio.to_thread(
            self.backend.click,
            x=position[0],
            y=position[1],
            button=kwargs["button"],
            clicks=kwargs["clicks"],
            interval=kwargs["interval"],
        )

    async def move(self, **kwargs: object) -> None:
        position = kwargs["position"]
        if not isinstance(position, tuple):
            raise TypeError("mouse position must be a tuple")
        await asyncio.to_thread(
            self.backend.moveTo, position[0], position[1], duration=kwargs["duration"]
        )

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
        await asyncio.to_thread(
            self.backend.dragTo,
            position[0],
            position[1],
            duration=kwargs["duration"],
            button=kwargs["button"],
        )

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


def _position(kwargs: dict[str, object]) -> tuple[int, int]:
    position = kwargs["position"]
    if not isinstance(position, tuple):
        raise TypeError("mouse position must be a tuple")
    return position

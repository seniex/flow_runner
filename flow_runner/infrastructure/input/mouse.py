import asyncio
import importlib
from typing import Any, Protocol


class MouseDevice(Protocol):
    async def click(self, **kwargs: object) -> None: ...
    async def move(self, **kwargs: object) -> None: ...
    async def scroll(self, **kwargs: object) -> None: ...


class PyAutoGuiMouseDevice:
    def __init__(self, backend: Any | None = None) -> None:
        if backend is None:
            backend = importlib.import_module("pyautogui")
        self.backend = backend

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

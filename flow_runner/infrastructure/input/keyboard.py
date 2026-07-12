import asyncio
import importlib
from typing import Any, Protocol


class KeyboardDevice(Protocol):
    async def press(self, key: str, count: int, interval: float) -> None: ...
    async def hotkey(self, keys: tuple[str, ...]) -> None: ...
    async def write(self, text: str, interval: float) -> None: ...


class PyAutoGuiKeyboardDevice:
    def __init__(self, backend: Any | None = None) -> None:
        if backend is None:
            backend = importlib.import_module("pyautogui")
        self.backend = backend

    async def press(self, key: str, count: int, interval: float) -> None:
        await asyncio.to_thread(self.backend.press, key, presses=count, interval=interval)

    async def hotkey(self, keys: tuple[str, ...]) -> None:
        await asyncio.to_thread(self.backend.hotkey, *keys)

    async def write(self, text: str, interval: float) -> None:
        await asyncio.to_thread(self.backend.write, text, interval=interval)

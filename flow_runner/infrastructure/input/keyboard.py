import asyncio
import importlib
import threading
from typing import Any, Protocol


class KeyboardDevice(Protocol):
    async def press(self, key: str, count: int, interval: float) -> None: ...
    async def hotkey(self, keys: tuple[str, ...]) -> None: ...
    async def write(self, text: str, interval: float) -> None: ...
    async def key_down(self, key: str) -> None: ...
    async def key_up(self, key: str) -> None: ...
    def release_all(self) -> None: ...


class PyAutoGuiKeyboardDevice:
    def __init__(self, backend: Any | None = None) -> None:
        if backend is None:
            backend = importlib.import_module("pyautogui")
        self.backend = backend
        self._held_keys: set[str] = set()
        self._state_lock = threading.Lock()

    async def press(self, key: str, count: int, interval: float) -> None:
        await asyncio.to_thread(self.backend.press, key, presses=count, interval=interval)

    async def hotkey(self, keys: tuple[str, ...]) -> None:
        await asyncio.to_thread(self.backend.hotkey, *keys)

    async def write(self, text: str, interval: float) -> None:
        await asyncio.to_thread(self.backend.write, text, interval=interval)

    async def key_down(self, key: str) -> None:
        await asyncio.to_thread(self._key_down, key)

    async def key_up(self, key: str) -> None:
        await asyncio.to_thread(self._key_up, key)

    def release_all(self) -> None:
        with self._state_lock:
            keys = tuple(self._held_keys)
            self._held_keys.clear()
            for key in keys:
                try:
                    self.backend.keyUp(key)
                except Exception:
                    continue

    def _key_down(self, key: str) -> None:
        with self._state_lock:
            self.backend.keyDown(key)
            self._held_keys.add(key)

    def _key_up(self, key: str) -> None:
        with self._state_lock:
            self.backend.keyUp(key)
            self._held_keys.discard(key)

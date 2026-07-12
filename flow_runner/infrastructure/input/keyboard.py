import asyncio
import ctypes
import importlib
import threading
import time
from collections.abc import Callable
from ctypes import wintypes
from typing import Any, Literal, Protocol

TextMode = Literal["keys", "unicode", "clipboard"]


class KeyboardDevice(Protocol):
    async def press(self, key: str, count: int, interval: float) -> None: ...
    async def hotkey(self, keys: tuple[str, ...]) -> None: ...
    async def write(self, text: str, interval: float, mode: TextMode = "keys") -> None: ...
    async def key_down(self, key: str) -> None: ...
    async def key_up(self, key: str) -> None: ...
    def release_all(self) -> None: ...


class PyAutoGuiKeyboardDevice:
    def __init__(
        self,
        backend: Any | None = None,
        *,
        unicode_writer: Callable[[str], None] | None = None,
        clipboard_paster: Callable[[str], None] | None = None,
    ) -> None:
        if backend is None:
            backend = importlib.import_module("pyautogui")
        self.backend = backend
        self.unicode_writer = unicode_writer or _send_unicode_text
        self.clipboard_paster = clipboard_paster or (
            lambda text: _paste_with_restored_clipboard(self.backend, text)
        )
        self._held_keys: set[str] = set()
        self._state_lock = threading.Lock()

    async def press(self, key: str, count: int, interval: float) -> None:
        for index in range(count):
            await asyncio.to_thread(self.backend.press, key, presses=1, interval=0.0)
            if interval > 0 and index + 1 < count:
                await asyncio.sleep(interval)

    async def hotkey(self, keys: tuple[str, ...]) -> None:
        await asyncio.to_thread(self.backend.hotkey, *keys)

    async def write(self, text: str, interval: float, mode: TextMode = "keys") -> None:
        if mode == "clipboard":
            await asyncio.to_thread(self.clipboard_paster, text)
            return
        for index, character in enumerate(text):
            if mode == "keys":
                await asyncio.to_thread(self.backend.write, character, interval=0.0)
            else:
                await asyncio.to_thread(self.unicode_writer, character)
            if interval > 0 and index + 1 < len(text):
                await asyncio.sleep(interval)

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


def _send_unicode_text(text: str) -> None:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    keyeventf_unicode = 0x0004
    keyeventf_keyup = 0x0002
    input_keyboard = 1

    class MouseInput(ctypes.Structure):
        _fields_ = [
            ("x", wintypes.LONG),
            ("y", wintypes.LONG),
            ("mouse_data", wintypes.DWORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("extra_info", wintypes.WPARAM),
        ]

    class KeyboardInput(ctypes.Structure):
        _fields_ = [
            ("virtual_key", wintypes.WORD),
            ("scan_code", wintypes.WORD),
            ("flags", wintypes.DWORD),
            ("time", wintypes.DWORD),
            ("extra_info", wintypes.WPARAM),
        ]

    class HardwareInput(ctypes.Structure):
        _fields_ = [
            ("message", wintypes.DWORD),
            ("parameter_low", wintypes.WORD),
            ("parameter_high", wintypes.WORD),
        ]

    class InputUnion(ctypes.Union):
        _fields_ = [
            ("mouse", MouseInput),
            ("keyboard", KeyboardInput),
            ("hardware", HardwareInput),
        ]

    class Input(ctypes.Structure):
        _anonymous_ = ("value",)
        _fields_ = [("type", wintypes.DWORD), ("value", InputUnion)]

    user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int)
    user32.SendInput.restype = wintypes.UINT

    units = text.encode("utf-16-le")
    for offset in range(0, len(units), 2):
        scan_code = int.from_bytes(units[offset : offset + 2], "little")
        events = (Input * 2)(
            Input(
                type=input_keyboard,
                value=InputUnion(
                    keyboard=KeyboardInput(
                        scan_code=scan_code,
                        flags=keyeventf_unicode,
                    )
                ),
            ),
            Input(
                type=input_keyboard,
                value=InputUnion(
                    keyboard=KeyboardInput(
                        scan_code=scan_code,
                        flags=keyeventf_unicode | keyeventf_keyup,
                    )
                ),
            ),
        )
        if user32.SendInput(2, events, ctypes.sizeof(Input)) != 2:
            raise ctypes.WinError(ctypes.get_last_error())


def _paste_with_restored_clipboard(backend: Any, text: str) -> None:
    clipboard = importlib.import_module("win32clipboard")
    snapshot = _clipboard_snapshot(clipboard)
    try:
        _open_clipboard(clipboard)
        try:
            clipboard.EmptyClipboard()
            clipboard.SetClipboardData(clipboard.CF_UNICODETEXT, text)
        finally:
            clipboard.CloseClipboard()
        backend.hotkey("ctrl", "v")
        time.sleep(0.05)
    finally:
        _restore_clipboard(clipboard, snapshot)


def _clipboard_snapshot(clipboard: Any) -> list[tuple[int, Any]]:
    _open_clipboard(clipboard)
    snapshot: list[tuple[int, Any]] = []
    try:
        format_id = 0
        while True:
            format_id = clipboard.EnumClipboardFormats(format_id)
            if not format_id:
                break
            try:
                snapshot.append((format_id, clipboard.GetClipboardData(format_id)))
            except Exception:
                continue
    finally:
        clipboard.CloseClipboard()
    return snapshot


def _restore_clipboard(clipboard: Any, snapshot: list[tuple[int, Any]]) -> None:
    _open_clipboard(clipboard)
    try:
        clipboard.EmptyClipboard()
        for format_id, data in snapshot:
            try:
                clipboard.SetClipboardData(format_id, data)
            except Exception:
                continue
    finally:
        clipboard.CloseClipboard()


def _open_clipboard(clipboard: Any) -> None:
    for attempt in range(10):
        try:
            clipboard.OpenClipboard()
            return
        except Exception:
            if attempt == 9:
                raise
            time.sleep(0.01)

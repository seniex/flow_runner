from __future__ import annotations

import asyncio
import ctypes
import importlib
import ntpath
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from flow_runner.domain.window_targets import WindowTarget


class WindowQuery(Protocol):
    def query(self, target: WindowTarget) -> dict[str, Any]: ...


class WindowController(Protocol):
    async def activate(self, target: WindowTarget) -> dict[str, Any]: ...

    async def minimize(self, target: WindowTarget) -> dict[str, Any]: ...

    async def restore(self, target: WindowTarget) -> dict[str, Any]: ...

    async def move_resize(
        self, target: WindowTarget, geometry: tuple[int, int, int, int]
    ) -> dict[str, Any]: ...


class Win32WindowQuery:
    def __init__(self, backend: Any | None = None) -> None:
        self.backend = backend or _PyWin32WindowBackend()

    def query(self, target: WindowTarget) -> dict[str, Any]:
        return dict(self.backend.query(target))


class Win32WindowController:
    def __init__(self, backend: Any | None = None) -> None:
        self.backend = backend or _PyWin32WindowBackend()

    async def activate(self, target: WindowTarget) -> dict[str, Any]:
        return dict(await asyncio.to_thread(self.backend.activate, target))

    async def minimize(self, target: WindowTarget) -> dict[str, Any]:
        return dict(await asyncio.to_thread(self.backend.minimize, target))

    async def restore(self, target: WindowTarget) -> dict[str, Any]:
        return dict(await asyncio.to_thread(self.backend.restore, target))

    async def move_resize(
        self, target: WindowTarget, geometry: tuple[int, int, int, int]
    ) -> dict[str, Any]:
        return dict(await asyncio.to_thread(self.backend.move_resize, target, geometry))


@dataclass(frozen=True, slots=True)
class _WindowCandidate:
    handle: int
    title: str
    process_id: int | None
    process_name: str | None
    foreground: bool
    minimized: bool
    maximized: bool


class _PyWin32WindowBackend:
    def __init__(
        self,
        backend: Any | None = None,
        *,
        win32gui: Any | None = None,
        win32con: Any | None = None,
        win32process: Any | None = None,
        win32api: Any | None = None,
        process_name_for_pid: Callable[[int], str] | None = None,
        foreground_unlocker: Callable[[], None] | None = None,
        is_maximized: Callable[[int], bool] | None = None,
    ) -> None:
        del backend
        self.win32con = win32con or importlib.import_module("win32con")
        self.win32gui = win32gui or importlib.import_module("win32gui")
        self.win32process = win32process or importlib.import_module("win32process")
        self.win32api = (
            win32api
            if win32api is not None
            else importlib.import_module("win32api")
            if win32gui is None
            else None
        )
        self._process_name_for_pid = process_name_for_pid or _process_name_for_pid
        self._foreground_unlocker = foreground_unlocker or _send_wscript_alt
        pywin32_is_zoomed = getattr(self.win32gui, "IsZoomed", None)
        self._is_maximized = (
            is_maximized
            or (pywin32_is_zoomed if callable(pywin32_is_zoomed) else None)
            or _is_maximized
        )

    def query(self, target: WindowTarget) -> dict[str, Any]:
        selected_name, matches = self._matches(target)
        if not matches:
            return {
                "exists": False,
                "foreground": False,
                "title": "",
                "handle": None,
                "selected_handle": None,
                "matched_handles": [],
                "matched_windows": [],
                "selected_process_name": selected_name,
                "attempted_process_names": list(target.process_names),
            }
        selected = self._select(target, matches)
        return self._diagnostics(target, selected_name, matches, selected)

    def activate(self, target: WindowTarget) -> dict[str, Any]:
        _selected_name, matches = self._require_matches(target)
        selected = self._select(target, matches)
        if selected.minimized:
            self.win32gui.ShowWindow(selected.handle, self.win32con.SW_RESTORE)
        self._foreground(selected.handle)
        return self.query(target)

    def minimize(self, target: WindowTarget) -> dict[str, Any]:
        _selected_name, matches = self._require_matches(target)
        failed: list[int] = []
        for candidate in matches:
            self.win32gui.ShowWindow(candidate.handle, self.win32con.SW_MINIMIZE)
            if not self.win32gui.IsIconic(candidate.handle):
                self.win32gui.ShowWindow(
                    candidate.handle,
                    getattr(self.win32con, "SW_FORCEMINIMIZE", self.win32con.SW_MINIMIZE),
                )
            if not self.win32gui.IsIconic(candidate.handle):
                failed.append(candidate.handle)
        if failed:
            raise RuntimeError(f"failed to minimize window handles: {failed}")
        return self.query(target)

    def restore(self, target: WindowTarget) -> dict[str, Any]:
        _selected_name, matches = self._require_matches(target)
        previous_foreground = self.win32gui.GetForegroundWindow()
        for candidate in matches:
            self.win32gui.ShowWindow(candidate.handle, self.win32con.SW_RESTORE)
        failed = [
            candidate.handle for candidate in matches if self.win32gui.IsIconic(candidate.handle)
        ]
        if previous_foreground and self.win32gui.GetForegroundWindow() != previous_foreground:
            self._foreground(previous_foreground)
        if failed:
            raise RuntimeError(f"failed to restore window handles: {failed}")
        return self.query(target)

    def move_resize(
        self, target: WindowTarget, geometry: tuple[int, int, int, int]
    ) -> dict[str, Any]:
        _selected_name, matches = self._require_matches(target)
        selected = self._select(target, matches)
        x, y, width, height = geometry
        self.win32gui.SetWindowPos(
            selected.handle,
            None,
            x,
            y,
            width,
            height,
            self.win32con.SWP_NOZORDER,
        )
        return self.query(target)

    def _require_matches(self, target: WindowTarget) -> tuple[str | None, list[_WindowCandidate]]:
        selected_name, matches = self._matches(target)
        if not matches:
            selector = ", ".join(target.process_names) if target.process_names else target.title
            raise LookupError(f"window not found: {selector}")
        return selected_name, matches

    def _matches(self, target: WindowTarget) -> tuple[str | None, list[_WindowCandidate]]:
        candidates = self._enumerate()
        if target.process_names:
            for requested, normalized in zip(
                target.process_names,
                target.matching_process_names,
                strict=True,
            ):
                matches = [
                    candidate
                    for candidate in candidates
                    if candidate.process_name is not None
                    and candidate.process_name.casefold() == normalized
                ]
                if matches:
                    return requested, matches
            return None, []
        assert target.title is not None
        matches = [candidate for candidate in candidates if target.title in candidate.title]
        return None, matches[:1]

    def _enumerate(self) -> list[_WindowCandidate]:
        candidates: list[_WindowCandidate] = []
        foreground = self.win32gui.GetForegroundWindow()

        def visit(handle: int, _extra: object) -> None:
            if not self.win32gui.IsWindowVisible(handle):
                return
            title = self.win32gui.GetWindowText(handle)
            if not title:
                return
            process_id: int | None = None
            process_name: str | None = None
            try:
                _thread_id, process_id = self.win32process.GetWindowThreadProcessId(handle)
                process_name = ntpath.basename(self._process_name_for_pid(process_id))
            except Exception:
                if process_id is None:
                    process_name = None
            candidates.append(
                _WindowCandidate(
                    handle=handle,
                    title=title,
                    process_id=process_id,
                    process_name=process_name,
                    foreground=handle == foreground,
                    minimized=bool(self.win32gui.IsIconic(handle)),
                    maximized=bool(self._is_maximized(handle)),
                )
            )

        self.win32gui.EnumWindows(visit, None)
        return candidates

    @staticmethod
    def _select(target: WindowTarget, matches: list[_WindowCandidate]) -> _WindowCandidate:
        if target.title is not None:
            return matches[0]
        for candidate in matches:
            if candidate.foreground:
                return candidate
        for candidate in matches:
            if not candidate.minimized:
                return candidate
        return matches[0]

    @staticmethod
    def _diagnostics(
        target: WindowTarget,
        selected_name: str | None,
        matches: list[_WindowCandidate],
        selected: _WindowCandidate,
    ) -> dict[str, Any]:
        return {
            "exists": bool(matches),
            "foreground": any(candidate.foreground for candidate in matches),
            "title": selected.title,
            "handle": selected.handle,
            "selected_handle": selected.handle,
            "selected_process_name": selected.process_name or selected_name,
            "matched_handles": [candidate.handle for candidate in matches],
            "matched_windows": [
                {
                    "handle": candidate.handle,
                    "title": candidate.title,
                    "process_id": candidate.process_id,
                    "process_name": candidate.process_name,
                    "foreground": candidate.foreground,
                    "minimized": candidate.minimized,
                    "maximized": candidate.maximized,
                }
                for candidate in matches
            ],
            "attempted_process_names": list(target.process_names),
        }

    def _send_alt_tap(self) -> None:
        if self.win32api is None:
            return
        keybd_event = getattr(self.win32api, "keybd_event", None)
        if not callable(keybd_event):
            return
        keybd_event(0x12, 0, 0, 0)
        keybd_event(0x12, 0, 2, 0)

    def _foreground(self, handle: int) -> None:
        self.win32gui.SetForegroundWindow(handle)
        if self.win32gui.GetForegroundWindow() == handle:
            return
        self._send_alt_tap()
        self._foreground_unlocker()
        self.win32gui.SetForegroundWindow(handle)
        if self.win32gui.GetForegroundWindow() != handle:
            raise RuntimeError(f"failed to foreground window handle: {handle}")


def _send_wscript_alt() -> None:
    try:
        client = importlib.import_module("win32com.client")
        client.Dispatch("WScript.Shell").SendKeys("%")
    except Exception:
        return


def _is_maximized(handle: int) -> bool:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    is_zoomed = user32.IsZoomed
    is_zoomed.argtypes = [ctypes.c_void_p]
    is_zoomed.restype = ctypes.c_int
    return bool(is_zoomed(handle))


def _process_name_for_pid(process_id: int) -> str:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    open_process = kernel32.OpenProcess
    open_process.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    open_process.restype = ctypes.c_void_p
    close_handle = kernel32.CloseHandle
    close_handle.argtypes = [ctypes.c_void_p]
    close_handle.restype = ctypes.c_int
    query_name = kernel32.QueryFullProcessImageNameW
    query_name.argtypes = [
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_wchar),
        ctypes.POINTER(ctypes.c_uint32),
    ]
    query_name.restype = ctypes.c_int
    handle = open_process(0x1000, 0, process_id)
    if not handle:
        raise OSError(ctypes.get_last_error(), f"OpenProcess failed for PID {process_id}")
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        size = ctypes.c_uint32(len(buffer))
        if not query_name(handle, 0, buffer, ctypes.byref(size)):
            raise OSError(
                ctypes.get_last_error(),
                f"QueryFullProcessImageNameW failed for PID {process_id}",
            )
        return buffer.value
    finally:
        close_handle(handle)

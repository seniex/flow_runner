import ctypes
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from ctypes import wintypes

from PySide6.QtWidgets import QApplication, QWidget

WindowAffinityState = tuple[tuple[int, int], ...]
_WDA_EXCLUDEFROMCAPTURE = 0x00000011


@contextmanager
def temporarily_hidden_application(enabled: bool) -> Iterator[None]:
    if not enabled:
        yield
        return
    app = QApplication.instance()
    if not isinstance(app, QApplication):
        yield
        return
    visible: list[QWidget] = [widget for widget in app.topLevelWidgets() if widget.isVisible()]
    active = app.activeWindow()
    affinity_state = _exclude_windows_from_capture(visible)
    for widget in visible:
        widget.hide()
    app.processEvents()
    _flush_window_compositor()
    try:
        yield
    finally:
        _restore_window_affinities(affinity_state)
        for widget in visible:
            widget.show()
        if active in visible:
            active.raise_()
            active.activateWindow()
        app.processEvents()


def _flush_window_compositor() -> None:
    if sys.platform != "win32":
        return
    try:
        dwmapi = ctypes.WinDLL("dwmapi", use_last_error=True)
    except OSError:
        return
    flush = dwmapi.DwmFlush
    flush.restype = ctypes.c_long
    flush.argtypes = []
    flush()


def _exclude_windows_from_capture(widgets: list[QWidget]) -> WindowAffinityState:
    if sys.platform != "win32":
        return ()
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    get_affinity = user32.GetWindowDisplayAffinity
    get_affinity.restype = wintypes.BOOL
    get_affinity.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    set_affinity = user32.SetWindowDisplayAffinity
    set_affinity.restype = wintypes.BOOL
    set_affinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    state: list[tuple[int, int]] = []
    for widget in widgets:
        handle = int(widget.winId())
        previous = wintypes.DWORD()
        if not get_affinity(handle, ctypes.byref(previous)):
            continue
        if not set_affinity(handle, _WDA_EXCLUDEFROMCAPTURE):
            continue
        state.append((handle, int(previous.value)))
    return tuple(state)


def _restore_window_affinities(state: WindowAffinityState) -> None:
    if sys.platform != "win32" or not state:
        return
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    set_affinity = user32.SetWindowDisplayAffinity
    set_affinity.restype = wintypes.BOOL
    set_affinity.argtypes = [wintypes.HWND, wintypes.DWORD]
    for handle, affinity in state:
        set_affinity(handle, affinity)

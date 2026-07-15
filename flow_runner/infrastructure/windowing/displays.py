import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from typing import Protocol

Rect = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class PhysicalDisplay:
    name: str
    rect: Rect


class PhysicalDisplayProvider(Protocol):
    def displays(self) -> tuple[PhysicalDisplay, ...]: ...


class WindowsPhysicalDisplayProvider:
    def displays(self) -> tuple[PhysicalDisplay, ...]:
        return _enumerate_windows_displays()


class _MonitorInfoExW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


def _enumerate_windows_displays() -> tuple[PhysicalDisplay, ...]:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    result: list[PhysicalDisplay] = []
    monitor_handle = wintypes.HANDLE
    device_context = wintypes.HANDLE
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        monitor_handle,
        device_context,
        ctypes.POINTER(wintypes.RECT),
        wintypes.LPARAM,
    )

    def visit(
        monitor: wintypes.HANDLE,
        context: wintypes.HANDLE,
        rect: object,
        data: wintypes.LPARAM,
    ) -> bool:
        del context, rect, data
        info = _MonitorInfoExW()
        info.cbSize = ctypes.sizeof(info)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return False
        bounds = info.rcMonitor
        result.append(
            PhysicalDisplay(
                str(info.szDevice),
                (bounds.left, bounds.top, bounds.right, bounds.bottom),
            )
        )
        return True

    callback = callback_type(visit)
    user32.GetMonitorInfoW.restype = wintypes.BOOL
    user32.GetMonitorInfoW.argtypes = [
        monitor_handle,
        ctypes.POINTER(_MonitorInfoExW),
    ]
    user32.EnumDisplayMonitors.restype = wintypes.BOOL
    user32.EnumDisplayMonitors.argtypes = [
        device_context,
        ctypes.POINTER(wintypes.RECT),
        callback_type,
        wintypes.LPARAM,
    ]
    if not user32.EnumDisplayMonitors(None, None, callback, 0):
        raise OSError(ctypes.get_last_error(), "无法枚举显示器")
    if not result:
        raise OSError("未找到可用显示器")
    return tuple(result)

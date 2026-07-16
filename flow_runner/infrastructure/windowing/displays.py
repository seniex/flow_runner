import ctypes
from ctypes import wintypes
from dataclasses import dataclass
from typing import Protocol

Rect = tuple[int, int, int, int]


@dataclass(frozen=True, slots=True)
class PhysicalDisplay:
    name: str
    rect: Rect
    aliases: tuple[str, ...] = ()


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


class _DisplayDeviceW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("DeviceName", wintypes.WCHAR * 32),
        ("DeviceString", wintypes.WCHAR * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", wintypes.WCHAR * 128),
        ("DeviceKey", wintypes.WCHAR * 128),
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
        name = str(info.szDevice)
        result.append(
            PhysicalDisplay(
                name,
                (bounds.left, bounds.top, bounds.right, bounds.bottom),
                _windows_display_aliases(name),
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


def _windows_display_aliases(device_name: str) -> tuple[str, ...]:
    try:
        device_id = _monitor_device_id(device_name)
        if not device_id:
            return ()
        aliases = _monitor_names_from_registry(device_id)
    except (OSError, ValueError):
        return ()
    return _normalize_display_aliases([(device_name, alias) for alias in aliases]).get(
        device_name.casefold(), ()
    )


def _monitor_device_id(device_name: str) -> str:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    monitor = _DisplayDeviceW()
    monitor.cb = ctypes.sizeof(monitor)
    user32.EnumDisplayDevicesW.restype = wintypes.BOOL
    user32.EnumDisplayDevicesW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.POINTER(_DisplayDeviceW),
        wintypes.DWORD,
    ]
    if not user32.EnumDisplayDevicesW(device_name, 0, ctypes.byref(monitor), 0):
        return ""
    return str(monitor.DeviceID)


def _monitor_names_from_registry(device_id: str) -> tuple[str, ...]:
    import winreg

    parts = device_id.split("\\")
    if len(parts) < 2 or parts[0].casefold() != "monitor":
        return ()
    path = rf"SYSTEM\CurrentControlSet\Enum\DISPLAY\{parts[1]}"
    names: list[str] = []
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as product_key:
        instance_count = winreg.QueryInfoKey(product_key)[0]
        for index in range(instance_count):
            instance = winreg.EnumKey(product_key, index)
            try:
                with winreg.OpenKey(
                    product_key,
                    instance + r"\Device Parameters",
                ) as parameters:
                    edid, _value_type = winreg.QueryValueEx(parameters, "EDID")
            except OSError:
                continue
            if isinstance(edid, bytes):
                name = _edid_monitor_name(edid)
                if name:
                    names.append(name)
    return tuple(names)


def _edid_monitor_name(edid: bytes) -> str:
    for offset in (54, 72, 90, 108):
        descriptor = edid[offset : offset + 18]
        if len(descriptor) == 18 and descriptor[:3] == b"\x00\x00\x00" and descriptor[3] == 0xFC:
            return (
                descriptor[5:18]
                .split(b"\n", 1)[0]
                .rstrip(b"\x00 ")
                .decode("ascii", errors="ignore")
            )
    return ""


def _normalize_display_aliases(
    pairs: list[tuple[str, str]],
) -> dict[str, tuple[str, ...]]:
    normalized: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}
    for device_name, alias in pairs:
        key = device_name.casefold()
        value = alias.strip()
        folded = value.casefold()
        if not value or folded in seen.setdefault(key, set()):
            continue
        seen[key].add(folded)
        normalized.setdefault(key, []).append(value)
    return {key: tuple(values) for key, values in normalized.items()}

from __future__ import annotations

import ctypes
import sys
from typing import Any, Protocol


class DpiApi(Protocol):
    def set_per_monitor_v2(self) -> bool: ...

    def set_per_monitor(self) -> bool: ...

    def set_system_aware(self) -> bool: ...


def enable_per_monitor_dpi_awareness(
    *,
    platform: str | None = None,
    api: DpiApi | None = None,
) -> str:
    if (platform or sys.platform) != "win32":
        return "not_windows"
    dpi_api = api or _WindowsDpiApi()
    for name, setter in (
        ("per_monitor_v2", dpi_api.set_per_monitor_v2),
        ("per_monitor", dpi_api.set_per_monitor),
        ("system", dpi_api.set_system_aware),
    ):
        try:
            if setter():
                return name
        except (AttributeError, OSError, TypeError):
            continue
    return "unchanged"


class _WindowsDpiApi:
    def __init__(self) -> None:
        loader = ctypes.WinDLL
        self.user32 = loader("user32", use_last_error=True)
        self.shcore: Any
        try:
            self.shcore = loader("shcore", use_last_error=True)
        except OSError:
            self.shcore = None

    def set_per_monitor_v2(self) -> bool:
        context = ctypes.c_void_p(-4)
        return bool(self.user32.SetProcessDpiAwarenessContext(context))

    def set_per_monitor(self) -> bool:
        if self.shcore is None:
            return False
        return int(self.shcore.SetProcessDpiAwareness(2)) == 0

    def set_system_aware(self) -> bool:
        return bool(self.user32.SetProcessDPIAware())

from __future__ import annotations

import ctypes
import sys
from collections.abc import Callable

IdentityApi = Callable[[str], int]


def set_windows_app_user_model_id(
    app_id: str = "FlowRunner.Qt",
    *,
    platform: str | None = None,
    api: IdentityApi | None = None,
) -> bool:
    platform = platform or sys.platform
    if platform != "win32":
        return False
    try:
        setter = api
        if setter is None:
            shell32 = ctypes.WinDLL("shell32", use_last_error=True)
            setter = shell32.SetCurrentProcessExplicitAppUserModelID
            setter.argtypes = [ctypes.c_wchar_p]
            setter.restype = ctypes.c_long
        return setter(app_id) == 0
    except (AttributeError, OSError, TypeError):
        return False

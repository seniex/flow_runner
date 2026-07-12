from enum import StrEnum

from flow_runner.domain.errors import ConditionError


class WindowCaptureMode(StrEnum):
    FOREGROUND = "foreground"
    BACKGROUND = "background"


def parse_window_capture_target(
    target: str,
    default_mode: WindowCaptureMode = WindowCaptureMode.FOREGROUND,
) -> tuple[WindowCaptureMode, str]:
    if not target.startswith("window:"):
        raise ConditionError(f"window capture cannot capture target '{target}'")
    value = target.removeprefix("window:")
    for mode in WindowCaptureMode:
        prefix = f"{mode.value}:"
        if value.startswith(prefix):
            title = value.removeprefix(prefix).strip()
            break
    else:
        mode = default_mode
        title = value.strip()
    if not title:
        raise ConditionError("window capture target requires a title")
    return mode, title


def canonical_capture_target(target: str) -> str:
    if not target.startswith("window:"):
        return target
    _mode, title = parse_window_capture_target(target)
    return f"window:{title}"

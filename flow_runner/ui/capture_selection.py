from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtWidgets import QWidget

from flow_runner.infrastructure.capture.base import CapturedFrame
from flow_runner.ui.application_visibility import temporarily_hidden_application
from flow_runner.ui.capture_preferences import CapturePreferences
from flow_runner.ui.native_capture_overlay import (
    Point,
    Region,
    SelectionMode,
    select_from_frame,
)

FrameProvider = Callable[[str], CapturedFrame]
Selector = Callable[
    [CapturedFrame, SelectionMode, QWidget | None],
    Point | Region | None,
]


@dataclass(frozen=True, slots=True)
class SelectionCapture:
    value: Point | Region
    frame: CapturedFrame


class CaptureSelectionSession:
    def __init__(
        self,
        frame_provider: FrameProvider,
        preferences: CapturePreferences,
        *,
        selector: Selector = select_from_frame,
    ) -> None:
        self._frame_provider = frame_provider
        self._preferences = preferences
        self._selector = selector

    def select(
        self,
        target: str,
        mode: SelectionMode,
        parent: QWidget | None = None,
    ) -> SelectionCapture | None:
        with temporarily_hidden_application(self._preferences.hide_application):
            frame = self._frame_provider(target)
            value = self._selector(frame, mode, parent)
        return None if value is None else SelectionCapture(value, frame)

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, cast

from PySide6.QtWidgets import QWidget

from flow_runner.ui.capture_selection import CaptureSelectionSession
from flow_runner.ui.native_capture_overlay import Region, SelectionMode


@dataclass(frozen=True, slots=True)
class TemplateCapture:
    region: Region
    path: Path


class RegionCaptureService:
    def __init__(
        self,
        session: CaptureSelectionSession,
        *,
        template_directory: Path,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._session = session
        self._template_directory = template_directory
        self._now = now

    @property
    def template_directory(self) -> Path:
        return self._template_directory

    def pick_region(
        self,
        target: str,
        parent: QWidget | None = None,
    ) -> Region | None:
        captured = self._session.select(target, SelectionMode.REGION, parent)
        return None if captured is None else cast(Region, captured.value)

    def capture_template(
        self,
        target: str,
        parent: QWidget | None = None,
    ) -> TemplateCapture | None:
        captured = self._session.select(target, SelectionMode.REGION, parent)
        if captured is None:
            return None
        region = cast(Region, captured.value)
        self._template_directory.mkdir(parents=True, exist_ok=True)
        timestamp = self._now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        path = self._template_directory / f"template_{timestamp}.png"
        captured.frame.image.crop(region).save(path, format="PNG")
        return TemplateCapture(region, path)


@dataclass(frozen=True, slots=True)
class PointCapture:
    position: tuple[int, int]
    coordinate_space: Literal["screen", "target"]


class PointCaptureService:
    def __init__(self, session: CaptureSelectionSession) -> None:
        self._session = session

    def pick_point(
        self,
        target: str,
        parent: QWidget | None = None,
    ) -> PointCapture | None:
        captured = self._session.select(target, SelectionMode.POINT, parent)
        if captured is None:
            return None
        x, y = cast(tuple[int, int], captured.value)
        if target == "desktop":
            return PointCapture(
                (x + captured.frame.origin[0], y + captured.frame.origin[1]),
                "screen",
            )
        if target.startswith("window:"):
            return PointCapture((x, y), "target")
        raise ValueError(f"不支持的鼠标目标：{target}")

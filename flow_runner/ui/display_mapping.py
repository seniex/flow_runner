from dataclasses import dataclass
from typing import Protocol

from PySide6.QtCore import QRect
from PySide6.QtGui import QGuiApplication

from flow_runner.infrastructure.capture.base import CapturedFrame
from flow_runner.infrastructure.windowing.displays import (
    PhysicalDisplayProvider,
    WindowsPhysicalDisplayProvider,
)

Point = tuple[int, int]
Rect = tuple[int, int, int, int]


class ScreenGeometry(Protocol):
    def name(self) -> str: ...

    def geometry(self) -> QRect: ...


@dataclass(frozen=True, slots=True)
class DisplayGeometry:
    name: str
    logical: Rect
    physical: Rect


@dataclass(frozen=True, slots=True)
class DisplayMapping:
    display: DisplayGeometry
    logical_region: Rect
    physical_region: Rect
    frame_region: Rect

    def logical_to_frame(self, point: Point) -> Point:
        physical = _scale_point(point, self.display.logical, self.display.physical)
        return (
            physical[0] - self.physical_region[0] + self.frame_region[0],
            physical[1] - self.physical_region[1] + self.frame_region[1],
        )

    def frame_to_logical(self, point: Point) -> Point:
        physical = (
            point[0] - self.frame_region[0] + self.physical_region[0],
            point[1] - self.frame_region[1] + self.physical_region[1],
        )
        return _scale_point(physical, self.display.physical, self.display.logical)


def build_display_mappings(
    *,
    frame_origin: Point,
    frame_size: Point,
    displays: tuple[DisplayGeometry, ...],
) -> tuple[DisplayMapping, ...]:
    frame_rect = (
        frame_origin[0],
        frame_origin[1],
        frame_origin[0] + frame_size[0],
        frame_origin[1] + frame_size[1],
    )
    mappings: list[DisplayMapping] = []
    for display in displays:
        physical = intersect_rects(frame_rect, display.physical)
        if physical is None:
            continue
        logical = _map_rect(physical, display.physical, display.logical)
        mappings.append(
            DisplayMapping(
                display=display,
                logical_region=logical,
                physical_region=physical,
                frame_region=(
                    physical[0] - frame_origin[0],
                    physical[1] - frame_origin[1],
                    physical[2] - frame_origin[0],
                    physical[3] - frame_origin[1],
                ),
            )
        )
    if not mappings:
        raise ValueError("捕获画面不与任何可用显示器相交")
    return tuple(mappings)


def display_mappings_for_frame(
    frame: CapturedFrame,
    *,
    screens: tuple[ScreenGeometry, ...] | None = None,
    physical_provider: PhysicalDisplayProvider | None = None,
) -> tuple[DisplayMapping, ...]:
    qt_screens: tuple[ScreenGeometry, ...] = (
        screens if screens is not None else tuple(QGuiApplication.screens())
    )
    provider = physical_provider or WindowsPhysicalDisplayProvider()
    physical = {display.name.casefold(): display for display in provider.displays()}
    geometries: list[DisplayGeometry] = []
    for screen in qt_screens:
        native = physical.get(screen.name().casefold())
        if native is None:
            raise ValueError(f"无法匹配显示器物理坐标：{screen.name()}")
        rect = screen.geometry()
        geometries.append(
            DisplayGeometry(
                screen.name(),
                (rect.x(), rect.y(), rect.x() + rect.width(), rect.y() + rect.height()),
                native.rect,
            )
        )
    return build_display_mappings(
        frame_origin=frame.origin,
        frame_size=frame.image.size,
        displays=tuple(geometries),
    )


def _scale_axis(
    value: int,
    source_start: int,
    source_end: int,
    target_start: int,
    target_end: int,
) -> int:
    if source_end <= source_start or target_end <= target_start:
        raise ValueError("显示器矩形尺寸必须为正数")
    bounded = max(source_start, min(value, source_end))
    ratio = (bounded - source_start) / (source_end - source_start)
    return round(target_start + ratio * (target_end - target_start))


def _scale_point(point: Point, source: Rect, target: Rect) -> Point:
    return (
        _scale_axis(point[0], source[0], source[2], target[0], target[2]),
        _scale_axis(point[1], source[1], source[3], target[1], target[3]),
    )


def _map_rect(rect: Rect, source: Rect, target: Rect) -> Rect:
    left, top = _scale_point((rect[0], rect[1]), source, target)
    right, bottom = _scale_point((rect[2], rect[3]), source, target)
    return left, top, right, bottom


def intersect_rects(first: Rect, second: Rect) -> Rect | None:
    result = (
        max(first[0], second[0]),
        max(first[1], second[1]),
        min(first[2], second[2]),
        min(first[3], second[3]),
    )
    return result if result[2] > result[0] and result[3] > result[1] else None


def contains(rect: Rect, point: Point) -> bool:
    return rect[0] <= point[0] < rect[2] and rect[1] <= point[1] < rect[3]

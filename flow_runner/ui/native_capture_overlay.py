from enum import StrEnum

from PIL import Image
from PySide6.QtCore import QEventLoop, QRect, Qt, Signal
from PySide6.QtGui import (
    QImage,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPaintEvent,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QWidget

from flow_runner.infrastructure.capture.base import CapturedFrame
from flow_runner.ui.display_mapping import (
    DisplayMapping,
    contains,
    display_mappings_for_frame,
    intersect_rects,
)

Point = tuple[int, int]
Region = tuple[int, int, int, int]


class SelectionMode(StrEnum):
    POINT = "point"
    REGION = "region"


class SelectionController:
    def __init__(
        self,
        mode: SelectionMode,
        mappings: tuple[DisplayMapping, ...],
    ) -> None:
        self.mode = mode
        self.mappings = mappings
        self.start: Point | None = None
        self.current: Point | None = None
        self.result: Point | Region | None = None
        self.finished = False

    def begin(self, logical_global: Point) -> None:
        self.start = self._to_frame(logical_global)
        self.current = self.start

    def update(self, logical_global: Point) -> None:
        if self.start is not None:
            self.current = self._to_frame(logical_global)

    def finish(self, logical_global: Point) -> None:
        point = self._to_frame(logical_global)
        if self.mode is SelectionMode.POINT:
            self.result = point
        elif self.start is not None:
            left, right = sorted((self.start[0], point[0]))
            top, bottom = sorted((self.start[1], point[1]))
            if right > left and bottom > top:
                self.result = (left, top, right, bottom)
        self.finished = self.result is not None

    def cancel(self) -> None:
        self.result = None
        self.finished = True

    def _to_frame(self, logical_global: Point) -> Point:
        for mapping in self.mappings:
            if contains(mapping.logical_region, logical_global):
                return mapping.logical_to_frame(logical_global)
        raise ValueError("选择位置不在捕获画面内")


class NativeCapturePane(QWidget):
    completed = Signal()

    def __init__(
        self,
        frame: CapturedFrame,
        mapping: DisplayMapping,
        controller: SelectionController,
    ) -> None:
        super().__init__(None)
        self.mapping = mapping
        self.controller = controller
        self._peers: tuple[NativeCapturePane, ...] = (self,)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        left, top, right, bottom = mapping.logical_region
        self.setGeometry(left, top, right - left, bottom - top)
        crop = frame.image.crop(mapping.frame_region)
        self._pixmap = QPixmap.fromImage(_pil_to_qimage(crop))
        physical_width = mapping.physical_region[2] - mapping.physical_region[0]
        logical_width = right - left
        self._pixmap.setDevicePixelRatio(physical_width / logical_width)

    def set_peers(self, panes: tuple["NativeCapturePane", ...]) -> None:
        self._peers = panes

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() is not Qt.MouseButton.LeftButton:
            return
        point = _global_point(event)
        if self.controller.mode is SelectionMode.POINT:
            self.controller.finish(point)
            self.completed.emit()
        else:
            self.controller.begin(point)
            self.grabMouse()
            self._update_all()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self.controller.start is not None:
            self.controller.update(_global_point(event))
            self._update_all()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() is not Qt.MouseButton.LeftButton:
            return
        self.releaseMouse()
        self.controller.finish(_global_point(event))
        self._update_all()
        if self.controller.finished:
            self.completed.emit()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self.controller.cancel()
            self.completed.emit()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.drawPixmap(self.rect(), self._pixmap)
        selection = _selection_rect_for_mapping(self.controller, self.mapping)
        if selection is not None:
            painter.setPen(QPen(self.palette().highlight().color(), 2))
            painter.drawRect(selection.translated(-self.x(), -self.y()))

    def _update_all(self) -> None:
        for pane in self._peers:
            pane.update()


def select_from_frame(
    frame: CapturedFrame,
    mode: SelectionMode,
    parent: QWidget | None = None,
    *,
    mappings: tuple[DisplayMapping, ...] | None = None,
) -> Point | Region | None:
    del parent
    resolved = mappings or display_mappings_for_frame(frame)
    controller = SelectionController(mode, resolved)
    loop = QEventLoop()
    panes = tuple(NativeCapturePane(frame, mapping, controller) for mapping in resolved)
    for pane in panes:
        pane.set_peers(panes)
        pane.completed.connect(loop.quit)
        pane.show()
    panes[0].activateWindow()
    panes[0].grabKeyboard()
    loop.exec()
    for pane in panes:
        pane.releaseKeyboard()
        pane.close()
        pane.deleteLater()
    return controller.result


def _global_point(event: QMouseEvent) -> Point:
    point = event.globalPosition()
    return round(point.x()), round(point.y())


def _selection_rect_for_mapping(
    controller: SelectionController,
    mapping: DisplayMapping,
) -> QRect | None:
    if controller.start is None or controller.current is None:
        return None
    frame_selection = (
        min(controller.start[0], controller.current[0]),
        min(controller.start[1], controller.current[1]),
        max(controller.start[0], controller.current[0]),
        max(controller.start[1], controller.current[1]),
    )
    overlap = intersect_rects(frame_selection, mapping.frame_region)
    if overlap is None:
        return None
    left, top = mapping.frame_to_logical((overlap[0], overlap[1]))
    right, bottom = mapping.frame_to_logical((overlap[2], overlap[3]))
    return QRect(left, top, right - left, bottom - top)


def _pil_to_qimage(image: Image.Image) -> QImage:
    rgba = image.convert("RGBA")
    raw = rgba.tobytes("raw", "RGBA")
    result = QImage(raw, rgba.width, rgba.height, QImage.Format.Format_RGBA8888)
    return result.copy()

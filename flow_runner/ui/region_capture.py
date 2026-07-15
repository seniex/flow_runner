from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL.Image import Image
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QImage, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QVBoxLayout, QWidget

from flow_runner.infrastructure.capture.base import CapturedFrame

Region = tuple[int, int, int, int]
FrameProvider = Callable[[str], CapturedFrame]
RegionSelector = Callable[[CapturedFrame, QWidget | None], Region | None]


@dataclass(frozen=True, slots=True)
class TemplateCapture:
    region: Region
    path: Path


class RegionCaptureService:
    def __init__(
        self,
        frame_provider: FrameProvider,
        *,
        selector: RegionSelector | None = None,
        template_directory: Path,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self._frame_provider = frame_provider
        self._selector = selector or select_region_from_frame
        self._template_directory = template_directory
        self._now = now

    @property
    def template_directory(self) -> Path:
        return self._template_directory

    def pick_region(self, target: str, parent: QWidget | None = None) -> Region | None:
        frame = self._frame_provider(target)
        return self._selector(frame, parent)

    def capture_template(
        self,
        target: str,
        parent: QWidget | None = None,
    ) -> TemplateCapture | None:
        frame = self._frame_provider(target)
        region = self._selector(frame, parent)
        if region is None:
            return None
        directory = self._template_directory
        directory.mkdir(parents=True, exist_ok=True)
        timestamp = self._now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        path = directory / f"template_{timestamp}.png"
        frame.image.crop(region).save(path, format="PNG")
        return TemplateCapture(region=region, path=path)


def map_selection_to_image(
    selection: Region,
    *,
    viewport_size: tuple[int, int],
    image_size: tuple[int, int],
) -> Region:
    viewport_width, viewport_height = viewport_size
    image_width, image_height = image_size
    if min(viewport_width, viewport_height, image_width, image_height) <= 0:
        raise ValueError("selection and image dimensions must be positive")
    scale = min(viewport_width / image_width, viewport_height / image_height)
    shown_width = image_width * scale
    shown_height = image_height * scale
    offset_x = (viewport_width - shown_width) / 2
    offset_y = (viewport_height - shown_height) / 2
    left, top, right, bottom = selection

    def image_x(value: int) -> int:
        return round(max(0.0, min(image_width, (value - offset_x) / scale)))

    def image_y(value: int) -> int:
        return round(max(0.0, min(image_height, (value - offset_y) / scale)))

    mapped = (image_x(left), image_y(top), image_x(right), image_y(bottom))
    if mapped[2] <= mapped[0] or mapped[3] <= mapped[1]:
        raise ValueError("selection does not overlap the captured image")
    return mapped


def select_region_from_frame(
    frame: CapturedFrame,
    parent: QWidget | None = None,
) -> Region | None:
    dialog = RegionSelectionDialog(frame.image, parent)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return None
    return dialog.region()


class RegionSelectionDialog(QDialog):
    def __init__(self, image: Image, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("regionSelectionDialog")
        self.setWindowTitle("框选检测区域")
        self.canvas = RegionSelectionCanvas(image)
        self.hint = QLabel("拖动鼠标框选区域，双击或点击确定完成；Esc 取消")
        self.hint.setObjectName("regionSelectionHint")
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        layout = QVBoxLayout(self)
        layout.addWidget(self.hint)
        layout.addWidget(self.canvas, 1)
        layout.addWidget(self.buttons)
        self.canvas.selectionChanged.connect(
            lambda region: self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(
                region is not None
            )
        )
        self.canvas.acceptRequested.connect(self.accept)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.resize(1000, 700)

    def accept(self) -> None:
        if self.canvas.region() is not None:
            super().accept()

    def region(self) -> Region:
        region = self.canvas.region()
        if region is None:
            raise RuntimeError("region selection dialog has no selection")
        return region


from PySide6.QtCore import Signal  # noqa: E402 - Qt signal belongs to the widget below


class RegionSelectionCanvas(QWidget):
    selectionChanged = Signal(object)
    acceptRequested = Signal()

    def __init__(self, image: Image) -> None:
        super().__init__()
        self.setObjectName("regionSelectionCanvas")
        self.setMinimumSize(480, 320)
        self._image_size = image.size
        self._pixmap = QPixmap.fromImage(_pil_to_qimage(image))
        self._start: QPoint | None = None
        self._end: QPoint | None = None

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._start = event.position().toPoint()
            self._end = self._start
            self.selectionChanged.emit(None)
            self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._start is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._end = event.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if self._start is None or event.button() != Qt.MouseButton.LeftButton:
            return
        self._end = event.position().toPoint()
        self.selectionChanged.emit(self.region())
        self.update()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.region() is not None:
            self.acceptRequested.emit()

    def paintEvent(self, event: object) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        target = _fitted_rect(self.size().width(), self.size().height(), *self._image_size)
        painter.drawPixmap(target, self._pixmap)
        selection = self._selection_rect()
        if selection is not None:
            painter.setPen(QPen(self.palette().highlight().color(), 2))
            painter.drawRect(selection)

    def region(self) -> Region | None:
        selection = self._selection_rect()
        if selection is None or selection.width() < 2 or selection.height() < 2:
            return None
        try:
            return map_selection_to_image(
                (selection.left(), selection.top(), selection.right() + 1, selection.bottom() + 1),
                viewport_size=(self.width(), self.height()),
                image_size=self._image_size,
            )
        except ValueError:
            return None

    def _selection_rect(self) -> QRect | None:
        if self._start is None or self._end is None:
            return None
        return QRect(self._start, self._end).normalized()


def _fitted_rect(
    viewport_width: int,
    viewport_height: int,
    image_width: int,
    image_height: int,
) -> QRect:
    scale = min(viewport_width / image_width, viewport_height / image_height)
    width = round(image_width * scale)
    height = round(image_height * scale)
    return QRect((viewport_width - width) // 2, (viewport_height - height) // 2, width, height)


def _pil_to_qimage(image: Image) -> QImage:
    rgba = image.convert("RGBA")
    raw = rgba.tobytes("raw", "RGBA")
    result = QImage(raw, rgba.width, rgba.height, QImage.Format.Format_RGBA8888)
    return result.copy()

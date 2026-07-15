import pytest
from PIL import Image
from PySide6.QtCore import QPoint, Qt

from flow_runner.infrastructure.capture.base import CapturedFrame
from flow_runner.ui.display_mapping import DisplayGeometry, DisplayMapping
from flow_runner.ui.native_capture_overlay import (
    NativeCapturePane,
    SelectionController,
    SelectionMode,
)


@pytest.fixture
def frame() -> CapturedFrame:
    return CapturedFrame(Image.new("RGB", (100, 80)), origin=(0, 0))


@pytest.fixture
def mapping() -> DisplayMapping:
    return DisplayMapping(
        DisplayGeometry("DISPLAY", (0, 0, 100, 80), (0, 0, 100, 80)),
        logical_region=(0, 0, 100, 80),
        physical_region=(0, 0, 100, 80),
        frame_region=(0, 0, 100, 80),
    )


@pytest.fixture
def left_mapping() -> DisplayMapping:
    return DisplayMapping(
        DisplayGeometry(
            "LEFT",
            (-1000, 0, 0, 1000),
            (-1000, 0, 0, 1000),
        ),
        logical_region=(-1000, 0, 0, 1000),
        physical_region=(-1000, 0, 0, 1000),
        frame_region=(0, 0, 1000, 1000),
    )


@pytest.fixture
def right_mapping() -> DisplayMapping:
    return DisplayMapping(
        DisplayGeometry(
            "RIGHT",
            (0, 0, 1000, 1000),
            (0, 0, 1000, 1000),
        ),
        logical_region=(0, 0, 1000, 1000),
        physical_region=(0, 0, 1000, 1000),
        frame_region=(1000, 0, 2000, 1000),
    )


def test_point_selection_finishes_on_single_click(mapping):
    controller = SelectionController(SelectionMode.POINT, (mapping,))
    controller.finish((50, 40))
    assert controller.result == (50, 40)
    assert controller.finished


def test_region_selection_finishes_on_release_without_confirmation(mapping):
    controller = SelectionController(SelectionMode.REGION, (mapping,))
    controller.begin((10, 20))
    controller.update((90, 70))
    controller.finish((90, 70))
    assert controller.result == (10, 20, 90, 70)
    assert controller.finished


def test_region_selection_can_cross_display_mappings(left_mapping, right_mapping):
    controller = SelectionController(
        SelectionMode.REGION,
        (left_mapping, right_mapping),
    )
    controller.begin((-100, 100))
    controller.finish((100, 300))
    assert controller.result == (900, 100, 1100, 300)


def test_escape_cancels_without_result(mapping):
    controller = SelectionController(SelectionMode.REGION, (mapping,))
    controller.cancel()
    assert controller.finished
    assert controller.result is None


def test_native_pane_completes_region_on_mouse_release(qtbot, frame, mapping):
    controller = SelectionController(SelectionMode.REGION, (mapping,))
    pane = NativeCapturePane(frame, mapping, controller)
    qtbot.addWidget(pane)
    pane.show()

    with qtbot.waitSignal(pane.completed):
        qtbot.mousePress(pane, Qt.MouseButton.LeftButton, pos=QPoint(10, 20))
        qtbot.mouseMove(pane, QPoint(60, 70))
        qtbot.mouseRelease(
            pane,
            Qt.MouseButton.LeftButton,
            pos=QPoint(60, 70),
        )

    assert controller.result == (10, 20, 60, 70)


def test_native_pane_escape_cancels(qtbot, frame, mapping):
    controller = SelectionController(SelectionMode.POINT, (mapping,))
    pane = NativeCapturePane(frame, mapping, controller)
    qtbot.addWidget(pane)
    pane.show()

    with qtbot.waitSignal(pane.completed):
        qtbot.keyClick(pane, Qt.Key.Key_Escape)

    assert controller.result is None
    assert controller.finished

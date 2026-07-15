from dataclasses import dataclass

import pytest
from PIL import Image
from PySide6.QtWidgets import QWidget

from flow_runner.infrastructure.capture.base import CapturedFrame
from flow_runner.ui.capture_selection import CaptureSelectionSession
from flow_runner.ui.native_capture_overlay import SelectionMode
from flow_runner.ui.region_capture import PointCapture, PointCaptureService


@dataclass
class FakePreferences:
    hide_application: bool


def test_selection_session_hides_before_capture_and_restores_after_selection(qtbot):
    events = []
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.show()
    preferences = FakePreferences(hide_application=True)

    def frame_provider(target):
        events.append(("capture", parent.isVisible(), target))
        return CapturedFrame(Image.new("RGB", (100, 80)), origin=(-10, 20))

    def selector(frame, mode, owner):
        events.append(("select", owner.isVisible(), mode, frame.origin))
        return (10, 20)

    session = CaptureSelectionSession(frame_provider, preferences, selector=selector)
    result = session.select("desktop", SelectionMode.POINT, parent)

    assert result is not None
    assert result.value == (10, 20)
    assert result.frame.origin == (-10, 20)
    assert events[0][:2] == ("capture", False)
    assert events[1][0:2] == ("select", False)
    assert parent.isVisible()


def test_selection_session_restores_after_cancel(qtbot):
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.show()
    session = CaptureSelectionSession(
        lambda target: CapturedFrame(Image.new("RGB", (20, 20))),
        FakePreferences(hide_application=True),
        selector=lambda frame, mode, owner: None,
    )
    assert session.select("desktop", SelectionMode.REGION, parent) is None
    assert parent.isVisible()


def test_selection_session_restores_after_selector_error(qtbot):
    parent = QWidget()
    qtbot.addWidget(parent)
    parent.show()

    def fail(frame, mode, owner):
        raise RuntimeError("overlay failed")

    session = CaptureSelectionSession(
        lambda target: CapturedFrame(Image.new("RGB", (20, 20))),
        FakePreferences(hide_application=True),
        selector=fail,
    )
    with pytest.raises(RuntimeError, match="overlay failed"):
        session.select("desktop", SelectionMode.REGION, parent)
    assert parent.isVisible()


@pytest.fixture
def session():
    return CaptureSelectionSession(
        lambda target: CapturedFrame(
            Image.new("RGB", (100, 80)),
            origin=(-100, 25),
        ),
        FakePreferences(hide_application=False),
        selector=lambda frame, mode, owner: (10, 20),
    )


@pytest.fixture
def cancelled_session():
    return CaptureSelectionSession(
        lambda target: CapturedFrame(Image.new("RGB", (100, 80))),
        FakePreferences(hide_application=False),
        selector=lambda frame, mode, owner: None,
    )


def test_desktop_point_adds_virtual_desktop_origin(session):
    service = PointCaptureService(session)
    selected = service.pick_point("desktop")
    assert selected == PointCapture(position=(-90, 45), coordinate_space="screen")


def test_window_point_stays_relative_to_captured_window(session):
    service = PointCaptureService(session)
    selected = service.pick_point("window:Game")
    assert selected == PointCapture(position=(10, 20), coordinate_space="target")


def test_cancel_keeps_point_empty(cancelled_session):
    assert PointCaptureService(cancelled_session).pick_point("desktop") is None

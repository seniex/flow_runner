import pytest
from PIL import Image
from PySide6.QtCore import QRect

from flow_runner.infrastructure.capture.base import CapturedFrame
from flow_runner.infrastructure.windowing.displays import PhysicalDisplay
from flow_runner.ui.display_mapping import (
    DisplayGeometry,
    build_display_mappings,
    display_mappings_for_frame,
)


class _Screen:
    def __init__(self, name, rect, device_pixel_ratio=1.0):
        self._name = name
        self._rect = rect
        self._device_pixel_ratio = device_pixel_ratio

    def name(self):
        return self._name

    def geometry(self):
        return self._rect

    def devicePixelRatio(self):
        return self._device_pixel_ratio


class _PhysicalDisplays:
    def __init__(self, *displays):
        self._displays = displays or (PhysicalDisplay(r"\\.\DISPLAY1", (-1920, 0, 0, 1080)),)

    def displays(self):
        return self._displays


def test_display_mapping_converts_150_percent_logical_points_to_frame_pixels():
    display = DisplayGeometry(
        name="DISPLAY1",
        logical=(0, 0, 1707, 960),
        physical=(0, 0, 2560, 1440),
    )
    mapping = build_display_mappings(
        frame_origin=(0, 0),
        frame_size=(2560, 1440),
        displays=(display,),
    )[0]

    assert mapping.logical_to_frame((853, 480)) == (1279, 720)
    assert mapping.frame_to_logical((1279, 720)) == (853, 480)


def test_display_mapping_handles_negative_secondary_monitor_origin():
    displays = (
        DisplayGeometry(
            name="LEFT",
            logical=(-1536, 0, 0, 864),
            physical=(-1920, 0, 0, 1080),
        ),
        DisplayGeometry(
            name="PRIMARY",
            logical=(0, 0, 2560, 1440),
            physical=(0, 0, 2560, 1440),
        ),
    )
    mappings = build_display_mappings(
        frame_origin=(-1920, 0),
        frame_size=(4480, 1440),
        displays=displays,
    )

    assert mappings[0].logical_to_frame((-768, 432)) == (960, 540)
    assert mappings[1].logical_to_frame((1280, 720)) == (3200, 720)


def test_display_mapping_crops_window_capture_to_display_intersections():
    displays = (
        DisplayGeometry("LEFT", (-1000, 0, 0, 800), (-1000, 0, 0, 800)),
        DisplayGeometry("RIGHT", (0, 0, 1000, 800), (0, 0, 1000, 800)),
    )
    mappings = build_display_mappings(
        frame_origin=(-200, 100),
        frame_size=(600, 400),
        displays=displays,
    )

    assert [mapping.frame_region for mapping in mappings] == [
        (0, 0, 200, 400),
        (200, 0, 600, 400),
    ]


def test_display_mapping_rejects_frame_outside_every_display():
    display = DisplayGeometry("PRIMARY", (0, 0, 100, 100), (0, 0, 100, 100))

    try:
        build_display_mappings(
            frame_origin=(200, 200),
            frame_size=(20, 20),
            displays=(display,),
        )
    except ValueError as error:
        assert str(error) == "捕获画面不与任何可用显示器相交"
    else:
        raise AssertionError("outside frame was accepted")


def test_display_mappings_for_frame_matches_qt_and_physical_display_names():
    frame = CapturedFrame(Image.new("RGB", (1920, 1080)), origin=(-1920, 0))
    screen = _Screen(r"\\.\display1", QRect(-1536, 0, 1536, 864))

    mappings = display_mappings_for_frame(
        frame,
        screens=(screen,),
        physical_provider=_PhysicalDisplays(),
    )

    assert mappings[0].display.logical == (-1536, 0, 0, 864)
    assert mappings[0].physical_region == (-1920, 0, 0, 1080)


def test_display_mapping_matches_qt_model_name_to_windows_device_alias():
    frame = CapturedFrame(Image.new("RGB", (2560, 1440)), origin=(0, 0))
    screen = _Screen("27E1Q", QRect(0, 0, 2560, 1440))
    provider = _PhysicalDisplays(
        PhysicalDisplay(
            r"\\.\DISPLAY1",
            (0, 0, 2560, 1440),
            aliases=("27E1Q",),
        )
    )

    mappings = display_mappings_for_frame(
        frame,
        screens=(screen,),
        physical_provider=provider,
    )

    assert mappings[0].display.name == "27E1Q"
    assert mappings[0].display.physical == (0, 0, 2560, 1440)


def test_display_mapping_uses_unique_dpi_aware_geometry_fallback():
    frame = CapturedFrame(Image.new("RGB", (2560, 1440)), origin=(0, 0))
    screen = _Screen("MODEL", QRect(0, 0, 1707, 960), 1.5)
    provider = _PhysicalDisplays(
        PhysicalDisplay(r"\\.\DISPLAY1", (0, 0, 2560, 1440)),
        PhysicalDisplay(r"\\.\DISPLAY2", (2560, 0, 4480, 1080)),
    )

    mappings = display_mappings_for_frame(
        frame,
        screens=(screen,),
        physical_provider=provider,
    )

    assert mappings[0].display.physical == (0, 0, 2560, 1440)


def test_display_mapping_rejects_ambiguous_geometry_fallback():
    frame = CapturedFrame(Image.new("RGB", (1920, 1080)), origin=(0, 0))
    screen = _Screen("MODEL", QRect(0, 0, 1920, 1080))
    provider = _PhysicalDisplays(
        PhysicalDisplay(r"\\.\DISPLAY1", (0, 0, 1920, 1080)),
        PhysicalDisplay(r"\\.\DISPLAY2", (1920, 0, 3840, 1080)),
    )

    with pytest.raises(ValueError, match="无法唯一匹配"):
        display_mappings_for_frame(
            frame,
            screens=(screen,),
            physical_provider=provider,
        )

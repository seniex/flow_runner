from flow_runner.infrastructure.windowing.displays import (
    PhysicalDisplay,
    _edid_monitor_name,
    _normalize_display_aliases,
)


def test_physical_display_exposes_device_name_and_pixel_rect():
    display = PhysicalDisplay("DISPLAY1", (-1920, 0, 0, 1080), aliases=("27E1Q",))

    assert display.name == "DISPLAY1"
    assert display.rect == (-1920, 0, 0, 1080)
    assert display.aliases == ("27E1Q",)


def test_display_aliases_are_normalized_and_deduplicated():
    assert _normalize_display_aliases(
        [
            (r"\\.\DISPLAY1", "27E1Q"),
            (r"\\.\display1", "27e1q"),
            (r"\\.\DISPLAY1", ""),
        ]
    ) == {r"\\.\display1": ("27E1Q",)}


def test_edid_monitor_name_reads_display_name_descriptor():
    edid = bytearray(128)
    edid[54:72] = b"\x00\x00\x00\xfc\x00" + b"27E1Q\n".ljust(13, b" ")

    assert _edid_monitor_name(bytes(edid)) == "27E1Q"

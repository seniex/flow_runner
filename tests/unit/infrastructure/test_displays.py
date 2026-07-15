from flow_runner.infrastructure.windowing.displays import PhysicalDisplay


def test_physical_display_exposes_device_name_and_pixel_rect():
    display = PhysicalDisplay("DISPLAY1", (-1920, 0, 0, 1080))

    assert display.name == "DISPLAY1"
    assert display.rect == (-1920, 0, 0, 1080)

import pytest

from flow_runner.infrastructure.windowing.geometry import Win32WindowGeometry


class _Backend:
    def __init__(self, *, rect=(300, 200, 900, 700), title="Game"):
        self.rect = rect
        self.title = title

    def EnumWindows(self, visit, extra):
        visit(10, extra)

    def IsWindowVisible(self, handle):
        return True

    def GetWindowText(self, handle):
        return self.title

    def GetWindowRect(self, handle):
        return self.rect


@pytest.mark.asyncio
async def test_window_geometry_resolves_capture_target_to_current_origin():
    geometry = Win32WindowGeometry(_Backend())

    assert await geometry.origin("window:background:Game") == (300, 200)


@pytest.mark.asyncio
async def test_window_geometry_rejects_missing_window():
    geometry = Win32WindowGeometry(_Backend(title="Other"))

    with pytest.raises(LookupError, match="找不到目标窗口：Game"):
        await geometry.origin("window:Game")


@pytest.mark.asyncio
async def test_window_geometry_rejects_invalid_window_rect():
    geometry = Win32WindowGeometry(_Backend(rect=(300, 200, 300, 700)))

    with pytest.raises(ValueError, match="目标窗口边界无效"):
        await geometry.origin("window:Game")

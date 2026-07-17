import pytest
from PIL import Image

from flow_runner.capabilities.conditions.pixel import PixelCondition, PixelConditionConfig
from flow_runner.capabilities.conditions.process import ProcessCondition, ProcessConditionConfig
from flow_runner.capabilities.conditions.region_change import (
    RegionChangeCondition,
    RegionChangeConditionConfig,
)
from flow_runner.capabilities.conditions.window import WindowCondition, WindowConditionConfig
from flow_runner.domain.enums import ConditionOutcome
from flow_runner.engine.perception import PerceptionService
from flow_runner.infrastructure.processes.query import WindowsProcessQuery
from flow_runner.infrastructure.windowing.win32 import Win32WindowQuery


class SequenceCapture:
    def __init__(self, images):
        self.images = iter(images)

    async def capture(self, target):
        return next(self.images)


@pytest.mark.asyncio
async def test_pixel_condition_respects_rgb_tolerance():
    image = Image.new("RGB", (10, 10), (100, 110, 120))
    condition = PixelCondition(PerceptionService(SequenceCapture([image])))
    result = await condition.evaluate(
        PixelConditionConfig(position=(5, 5), color=(104, 108, 121), tolerance=5), None
    )
    assert result.outcome is ConditionOutcome.MATCH


@pytest.mark.asyncio
async def test_region_change_compares_consecutive_frames():
    first = Image.new("RGB", (10, 10), "black")
    second = first.copy()
    for x in range(5):
        for y in range(10):
            second.putpixel((x, y), (255, 255, 255))
    condition = RegionChangeCondition(PerceptionService(SequenceCapture([first, second])))
    config = RegionChangeConditionConfig(region=(0, 0, 10, 10), threshold=0.4)
    initial = await condition.evaluate(config, None)
    changed = await condition.evaluate(config, None)
    assert initial.outcome is ConditionOutcome.NO_MATCH
    assert changed.outcome is ConditionOutcome.MATCH


@pytest.mark.asyncio
async def test_window_and_process_conditions_use_query_adapters():
    class Windows:
        def query(self, target):
            assert target.process_names == ("game.exe", "game-legacy.exe")
            return {
                "exists": True,
                "foreground": True,
                "title": "Game Window",
                "selected_process_name": "game.exe",
                "matched_handles": [42],
            }

    class Processes:
        def exists(self, name):
            return name == "game.exe"

    window = await WindowCondition(Windows()).evaluate(
        WindowConditionConfig(
            process_name="game.exe",
            fallback_process_names=["game-legacy.exe"],
            require_foreground=True,
        ),
        None,
    )
    process = await ProcessCondition(Processes()).evaluate(
        ProcessConditionConfig(name="game.exe"), None
    )
    assert window.outcome is ConditionOutcome.MATCH
    assert window.provider_data["matched_handles"] == [42]
    assert process.outcome is ConditionOutcome.MATCH


@pytest.mark.asyncio
async def test_window_condition_keeps_legacy_title_matching():
    class Windows:
        def query(self, target):
            assert target.title == "Game"
            return {"exists": True, "foreground": False, "title": "Game Window"}

    result = await WindowCondition(Windows()).evaluate(
        WindowConditionConfig(title="Game"),
        None,
    )

    assert result.outcome is ConditionOutcome.MATCH
    assert result.text == "Game Window"


def test_win32_window_query_normalizes_injected_backend_result():
    class Backend:
        def query(self, target):
            assert target.title == "Game"
            return {"exists": True, "foreground": True, "title": "Game Window", "handle": 42}

    assert Win32WindowQuery(Backend()).query(WindowConditionConfig(title="Game")) == {
        "exists": True,
        "foreground": True,
        "title": "Game Window",
        "handle": 42,
    }


def test_windows_process_query_matches_tasklist_rows_case_insensitively():
    query = WindowsProcessQuery(run_tasklist=lambda: '"Game.EXE","123","Console","1","10,000 K"\n')

    assert query.exists("game.exe")
    assert not query.exists("other.exe")

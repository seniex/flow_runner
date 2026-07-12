import io
import json

import pytest
from PIL import Image, ImageDraw

from flow_runner.capabilities.conditions.image import ImageCondition, ImageConditionConfig
from flow_runner.capabilities.conditions.ocr import OcrCondition, OcrConditionConfig
from flow_runner.domain.enums import ConditionOutcome
from flow_runner.domain.errors import ConditionError
from flow_runner.engine.perception import PerceptionService
from flow_runner.infrastructure.capture.base import CapturedFrame
from flow_runner.infrastructure.capture.desktop import DesktopCapture
from flow_runner.infrastructure.capture.targets import (
    TargetCapture,
    WindowCapture,
    WindowCaptureMode,
    canonical_capture_target,
)
from flow_runner.infrastructure.capture.windows_graphics import (
    WindowsCaptureFrameSource,
    WindowsGraphicsCapture,
)
from flow_runner.infrastructure.ocr.base import OcrItem, OcrObservation
from flow_runner.infrastructure.ocr.paddle_json import PaddleJsonOcr, PaddleJsonProcessClient
from flow_runner.infrastructure.ocr.tesseract import TesseractOcr


class StaticCapture:
    def __init__(self, image):
        self.image = image
        self.calls = 0

    async def capture(self, target):
        self.calls += 1
        return self.image.copy()


class FakeOcr:
    name = "fake-ocr"

    def __init__(self, observation):
        self.observation = observation
        self.calls = 0

    async def recognize(self, image, *, language, preprocessing):
        self.calls += 1
        return self.observation


@pytest.mark.asyncio
async def test_ocr_condition_preserves_or_and_keyword_grammar_and_position():
    capture = StaticCapture(Image.new("RGB", (200, 100), "white"))
    observation = OcrObservation(
        text="角色 已进入 战斗",
        items=[OcrItem(text="进入战斗", bounds=(30, 20, 90, 50), confidence=0.96)],
    )
    provider = OcrCondition(PerceptionService(capture), FakeOcr(observation))
    config = OcrConditionConfig(
        target="desktop",
        region=(10, 5, 110, 55),
        keywords="登录|进入,战斗",
    )

    result = await provider.evaluate(config, None)

    assert result.outcome is ConditionOutcome.MATCH
    assert result.text == "进入战斗"
    assert result.bounds == (40, 25, 100, 55)
    assert result.position == (70, 40)
    assert result.confidence == pytest.approx(0.96)


@pytest.mark.asyncio
async def test_ocr_condition_scales_input_and_normalizes_result_coordinates():
    capture = StaticCapture(Image.new("RGB", (200, 100), "white"))

    class ScaledOcr:
        name = "scaled"

        async def recognize(self, image, *, language, preprocessing):
            assert image.size == (200, 100)
            return OcrObservation(
                text="开始游戏",
                items=[
                    OcrItem(
                        text="开始游戏",
                        bounds=(40, 20, 160, 80),
                        confidence=0.9,
                    )
                ],
            )

    provider = OcrCondition(PerceptionService(capture), ScaledOcr())

    result = await provider.evaluate(
        OcrConditionConfig(
            region=(10, 5, 110, 55),
            keywords="开始游戏",
            scale=2,
        ),
        None,
    )

    assert result.bounds == (30, 15, 90, 45)
    assert result.position == (60, 30)


@pytest.mark.asyncio
async def test_visual_condition_translates_target_local_coordinates_to_screen_coordinates():
    class OffsetCapture:
        async def capture(self, target):
            return CapturedFrame(
                image=Image.new("RGB", (200, 100), "white"),
                origin=(-1920, 100),
            )

    observation = OcrObservation(
        text="开始",
        items=[OcrItem(text="开始", bounds=(30, 20, 90, 50), confidence=0.96)],
    )
    provider = OcrCondition(PerceptionService(OffsetCapture()), FakeOcr(observation))

    result = await provider.evaluate(
        OcrConditionConfig(region=(10, 5, 110, 55), keywords="开始"),
        None,
    )

    assert result.bounds == (-1880, 125, -1820, 155)
    assert result.position == (-1850, 140)


@pytest.mark.asyncio
async def test_visual_result_reports_capture_mode_and_fallback_reason():
    class FallbackCapture:
        async def capture(self, target):
            return CapturedFrame(
                Image.new("RGB", (100, 50), "white"),
                (10, 20),
                {
                    "requested_capture_mode": "background",
                    "capture_mode": "foreground",
                    "fallback_reason": "graphics timeout",
                },
            )

    provider = OcrCondition(
        PerceptionService(FallbackCapture()),
        FakeOcr(OcrObservation(text="开始", items=[OcrItem(text="开始")])),
    )

    result = await provider.evaluate(OcrConditionConfig(keywords="开始"), None)

    assert result.provider_data["requested_capture_mode"] == "background"
    assert result.provider_data["capture_mode"] == "foreground"
    assert result.provider_data["fallback_reason"] == "graphics timeout"


@pytest.mark.asyncio
async def test_image_condition_returns_absolute_match_coordinates(tmp_path):
    screen = Image.new("RGB", (160, 100), "black")
    draw = ImageDraw.Draw(screen)
    draw.rectangle((70, 40, 89, 59), fill="red")
    template = Image.new("RGB", (20, 20), "red")
    template_path = tmp_path / "target.png"
    template.save(template_path)
    provider = ImageCondition(PerceptionService(StaticCapture(screen)))
    config = ImageConditionConfig(
        target="desktop",
        region=(50, 20, 120, 80),
        template_path=template_path,
        threshold=0.99,
    )

    result = await provider.evaluate(config, None)

    assert result.outcome is ConditionOutcome.MATCH
    assert result.bounds == (70, 40, 90, 60)
    assert result.position == (80, 50)


@pytest.mark.asyncio
async def test_missing_template_is_a_condition_error(tmp_path):
    provider = ImageCondition(PerceptionService(StaticCapture(Image.new("RGB", (10, 10)))))
    config = ImageConditionConfig(template_path=tmp_path / "missing.png")

    with pytest.raises(ConditionError, match="missing.png"):
        await provider.evaluate(config, None)


@pytest.mark.asyncio
async def test_desktop_capture_uses_injected_grabber_without_import_side_effects():
    calls = 0

    def grabber():
        nonlocal calls
        calls += 1
        return Image.new("RGB", (12, 8), "blue")

    frame = await DesktopCapture(
        grabber=grabber,
        origin_provider=lambda: (-1280, 0),
    ).capture("desktop")

    assert frame.image.size == (12, 8)
    assert frame.origin == (-1280, 0)
    assert calls == 1


@pytest.mark.asyncio
async def test_window_capture_uses_window_bounds_and_preserves_origin():
    calls = []

    class Bounds:
        def bounds(self, title):
            assert title == "Game"
            return (-100, 50, 300, 250)

    def grabber(bounds):
        calls.append(bounds)
        return Image.new("RGB", (400, 200), "blue")

    frame = await WindowCapture(bounds=Bounds(), grabber=grabber).capture("window:Game")

    assert frame.origin == (-100, 50)
    assert frame.image.size == (400, 200)
    assert calls == [(-100, 50, 300, 250)]


@pytest.mark.asyncio
async def test_target_capture_routes_desktop_and_window_targets():
    calls = []

    class Adapter:
        def __init__(self, name):
            self.name = name

        async def capture(self, target):
            calls.append((self.name, target))
            return CapturedFrame(Image.new("RGB", (1, 1)), (0, 0))

    capture = TargetCapture(Adapter("desktop"), Adapter("window"))

    await capture.capture("desktop")
    await capture.capture("window:Game")

    assert calls == [("desktop", "desktop"), ("window", "window:Game")]


@pytest.mark.asyncio
async def test_target_capture_selects_default_and_explicit_window_modes():
    calls = []

    class Adapter:
        def __init__(self, name):
            self.name = name

        async def capture(self, target):
            calls.append((self.name, target))
            return CapturedFrame(Image.new("RGB", (2, 2)), (10, 20))

    capture = TargetCapture(
        Adapter("desktop"),
        Adapter("foreground"),
        background_window=Adapter("background"),
        default_window_mode=WindowCaptureMode.BACKGROUND,
    )

    default = await capture.capture("window:Game")
    foreground = await capture.capture("window:foreground:Game")
    background = await capture.capture("window:background:Game")

    assert calls == [
        ("background", "window:Game"),
        ("foreground", "window:Game"),
        ("background", "window:Game"),
    ]
    assert default.metadata["capture_mode"] == "background"
    assert foreground.metadata["capture_mode"] == "foreground"
    assert background.metadata["capture_mode"] == "background"
    assert canonical_capture_target("window:background:Game") == "window:Game"


@pytest.mark.asyncio
async def test_background_capture_fallback_is_explicit_in_frame_metadata():
    class Foreground:
        async def capture(self, target):
            return CapturedFrame(Image.new("RGB", (2, 2)), (1, 2))

    class Background:
        async def capture(self, target):
            raise ConditionError("graphics capture unavailable")

    capture = TargetCapture(
        StaticCapture(Image.new("RGB", (1, 1))),
        Foreground(),
        background_window=Background(),
        default_window_mode=WindowCaptureMode.BACKGROUND,
        fallback_to_foreground=True,
    )

    frame = await capture.capture("window:Game")

    assert frame.metadata["requested_capture_mode"] == "background"
    assert frame.metadata["capture_mode"] == "foreground"
    assert "graphics capture unavailable" in frame.metadata["fallback_reason"]


@pytest.mark.asyncio
async def test_background_capture_can_disable_foreground_fallback():
    class Foreground:
        async def capture(self, target):
            raise AssertionError("foreground fallback must stay disabled")

    class Background:
        async def capture(self, target):
            raise ConditionError("graphics timeout")

    capture = TargetCapture(
        StaticCapture(Image.new("RGB", (1, 1))),
        Foreground(),
        background_window=Background(),
        default_window_mode=WindowCaptureMode.BACKGROUND,
        fallback_to_foreground=False,
    )

    with pytest.raises(ConditionError, match="graphics timeout"):
        await capture.capture("window:Game")


@pytest.mark.asyncio
async def test_windows_graphics_capture_returns_rgb_frame_with_window_origin():
    calls = []

    class Locator:
        def locate(self, title):
            assert title == "Game"
            return 123, (-20, 30, 180, 130)

    class Source:
        async def capture(self, handle, timeout_seconds):
            calls.append((handle, timeout_seconds))
            return Image.new("RGB", (200, 100), (1, 2, 3))

    frame = await WindowsGraphicsCapture(
        locator=Locator(),
        source=Source(),
        timeout_seconds=1.5,
    ).capture("window:Game")

    assert frame.origin == (-20, 30)
    assert frame.image.getpixel((0, 0)) == (1, 2, 3)
    assert frame.metadata == {
        "capture_backend": "windows_graphics_capture",
        "window_handle": 123,
        "window_bounds": (-20, 30, 180, 130),
    }
    assert calls == [(123, 1.5)]


@pytest.mark.asyncio
async def test_windows_capture_frame_source_copies_bgra_and_stops_session():
    import numpy as np

    created = []

    class ExternalControl:
        def __init__(self):
            self.stop_calls = 0
            self.wait_calls = 0

        def stop(self):
            self.stop_calls += 1

        def wait(self):
            self.wait_calls += 1

    class InternalControl:
        def __init__(self):
            self.stopped = False

        def stop(self):
            self.stopped = True

    class Capture:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.handlers = {}
            self.external = ExternalControl()
            self.internal = InternalControl()
            created.append(self)

        def event(self, handler):
            self.handlers[handler.__name__] = handler
            return handler

        def start_free_threaded(self):
            frame = type(
                "Frame",
                (),
                {"frame_buffer": np.array([[[10, 20, 30, 255]]], dtype=np.uint8)},
            )()
            self.handlers["on_frame_arrived"](frame, self.internal)
            return self.external

    image = await WindowsCaptureFrameSource(Capture).capture(321, 1.0)

    assert image.getpixel((0, 0)) == (30, 20, 10)
    assert created[0].kwargs == {
        "cursor_capture": False,
        "draw_border": None,
        "window_hwnd": 321,
    }
    assert created[0].internal.stopped
    assert created[0].external.stop_calls == 1
    assert created[0].external.wait_calls == 1


@pytest.mark.asyncio
async def test_tesseract_adapter_normalizes_text_bounds_and_confidence():
    def image_to_data(image, **kwargs):
        assert image.size == (30, 20)
        assert kwargs["lang"] == "eng"
        return {
            "text": ["Start", ""],
            "left": [2, 0],
            "top": [3, 0],
            "width": [10, 0],
            "height": [5, 0],
            "conf": ["95.5", "-1"],
        }

    observation = await TesseractOcr(image_to_data=image_to_data).recognize(
        Image.new("RGB", (30, 20)),
        language="eng",
        preprocessing="",
    )

    assert observation.text == "Start"
    assert observation.items == [OcrItem(text="Start", bounds=(2, 3, 12, 8), confidence=0.955)]


@pytest.mark.asyncio
async def test_paddle_json_adapter_normalizes_client_response():
    class Client:
        async def recognize(self, image):
            assert image.size == (40, 30)
            return [
                {
                    "text": "战斗",
                    "score": 0.91,
                    "box": [[5, 6], [25, 6], [25, 16], [5, 16]],
                }
            ]

    observation = await PaddleJsonOcr(Client()).recognize(
        Image.new("RGB", (40, 30)), language="chi_sim", preprocessing=""
    )

    assert observation == OcrObservation(
        text="战斗",
        items=[OcrItem(text="战斗", bounds=(5, 6, 25, 16), confidence=0.91)],
    )


@pytest.mark.asyncio
async def test_paddle_json_process_client_sends_image_request_and_stops(tmp_path):
    created = []

    class Process:
        def __init__(self):
            self.stdin = io.StringIO()
            self.stdout = io.StringIO(
                "PaddleOCR-json init\n"
                + json.dumps(
                    {
                        "code": 100,
                        "data": [
                            {
                                "text": "开始",
                                "score": 0.9,
                                "box": [[1, 2], [3, 2], [3, 4], [1, 4]],
                            }
                        ],
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            self.terminated = False

        def poll(self):
            return 0 if self.terminated else None

        def terminate(self):
            self.terminated = True

        def wait(self, timeout=None):
            return 0

        def kill(self):
            self.terminated = True

    def factory(*args, **kwargs):
        process = Process()
        created.append((args, kwargs, process))
        return process

    executable = tmp_path / "PaddleOCR-json.exe"
    executable.write_bytes(b"")
    client = PaddleJsonProcessClient(executable, process_factory=factory)

    rows = await client.recognize(Image.new("RGB", (4, 4), "white"))
    request = json.loads(created[0][2].stdin.getvalue())
    client.stop()

    assert rows[0]["text"] == "开始"
    assert request["image_path"].endswith(".png")
    assert created[0][2].terminated

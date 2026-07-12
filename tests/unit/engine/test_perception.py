import asyncio

import pytest
from PIL import Image

from flow_runner.engine.perception import PerceptionService


class FakeCapture:
    def __init__(self):
        self.calls = 0

    async def capture(self, target):
        self.calls += 1
        await asyncio.sleep(0)
        return Image.new("RGB", (200, 100), (self.calls, 0, 0))


class FakeOcr:
    name = "fake-ocr"

    def __init__(self):
        self.calls = 0

    async def recognize(self, image, *, language, preprocessing):
        self.calls += 1
        return {
            "text": f"result-{self.calls}",
            "size": image.size,
            "language": language,
            "preprocessing": preprocessing,
        }


@pytest.mark.asyncio
async def test_concurrent_reads_share_one_frame():
    capture = FakeCapture()
    service = PerceptionService(capture, coalesce_window_ms=10)

    first, second = await asyncio.gather(
        service.snapshot("window:game"),
        service.snapshot("window:game"),
    )

    assert first.frame_id == second.frame_id
    assert capture.calls == 1


@pytest.mark.asyncio
async def test_ocr_cache_uses_frame_region_and_parameters():
    capture = FakeCapture()
    ocr = FakeOcr()
    service = PerceptionService(capture)
    snapshot = await service.snapshot("desktop")

    first = await service.ocr(
        snapshot,
        region=(0, 0, 100, 50),
        provider=ocr,
        language="chi_sim",
        preprocessing="scale:2",
    )
    second = await service.ocr(
        snapshot,
        region=(0, 0, 100, 50),
        provider=ocr,
        language="chi_sim",
        preprocessing="scale:2",
    )
    third = await service.ocr(
        snapshot,
        region=(0, 0, 100, 50),
        provider=ocr,
        language="eng",
        preprocessing="scale:2",
    )

    assert first is second
    assert third is not first
    assert first["size"] == (100, 50)
    assert ocr.calls == 2


@pytest.mark.asyncio
async def test_scene_change_invalidates_frame_and_ocr_cache():
    capture = FakeCapture()
    ocr = FakeOcr()
    service = PerceptionService(capture, coalesce_window_ms=1000)
    old = await service.snapshot("desktop")
    await service.ocr(old, region=None, provider=ocr)

    service.mark_scene_changed("desktop")
    new = await service.snapshot("desktop")
    await service.ocr(new, region=None, provider=ocr)

    assert new.frame_id != old.frame_id
    assert new.scene_generation == old.scene_generation + 1
    assert capture.calls == 2
    assert ocr.calls == 2


def test_crop_rejects_out_of_bounds_regions():
    capture = FakeCapture()
    service = PerceptionService(capture)
    image = Image.new("RGB", (20, 10))

    with pytest.raises(ValueError, match="bounds"):
        service.crop_image(image, (-1, 0, 10, 10))

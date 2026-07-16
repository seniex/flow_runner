import asyncio

import pytest

from flow_runner.domain.errors import Cancelled
from flow_runner.engine.cancellation import CancellationToken


@pytest.mark.asyncio
async def test_pause_blocks_checkpoint_until_resume():
    token = CancellationToken()
    token.pause()
    waiter = asyncio.create_task(token.wait_until_active())

    await asyncio.sleep(0)

    assert not waiter.done()
    token.resume()
    await asyncio.wait_for(waiter, timeout=0.2)


@pytest.mark.asyncio
async def test_cancel_wakes_a_paused_checkpoint():
    token = CancellationToken()
    token.pause()
    waiter = asyncio.create_task(token.wait_until_active())

    await asyncio.sleep(0)
    token.cancel()

    with pytest.raises(Cancelled, match="execution cancelled"):
        await asyncio.wait_for(waiter, timeout=0.2)


def test_active_time_excludes_paused_duration():
    now = 10.0
    token = CancellationToken(clock=lambda: now)

    now = 12.0
    token.pause()
    now = 17.0

    assert token.active_time() == pytest.approx(12.0)

    token.resume()
    now = 20.0

    assert token.active_time() == pytest.approx(15.0)


@pytest.mark.asyncio
async def test_pause_aware_sleep_preserves_remaining_active_delay():
    token = CancellationToken()
    sleeper = asyncio.create_task(token.sleep(0.08))

    await asyncio.sleep(0.02)
    token.pause()
    await asyncio.sleep(0.08)

    assert not sleeper.done()

    token.resume()
    await asyncio.wait_for(sleeper, timeout=0.12)


@pytest.mark.asyncio
async def test_pause_aware_sleep_cleans_up_children_when_caller_is_cancelled():
    token = CancellationToken()
    existing = set(asyncio.all_tasks())
    sleeper = asyncio.create_task(token.sleep(60))
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    sleeper.cancel()
    with pytest.raises(asyncio.CancelledError):
        await sleeper
    await asyncio.sleep(0)

    created = set(asyncio.all_tasks()).difference(existing)
    assert not created


@pytest.mark.asyncio
async def test_paused_checkpoint_cleans_up_children_when_caller_is_cancelled():
    token = CancellationToken()
    token.pause()
    existing = set(asyncio.all_tasks())
    waiter = asyncio.create_task(token.wait_until_active())
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    await asyncio.sleep(0)

    created = set(asyncio.all_tasks()).difference(existing)
    assert not created

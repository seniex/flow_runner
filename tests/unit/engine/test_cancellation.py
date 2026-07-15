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

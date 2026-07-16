import asyncio
from collections.abc import Callable
from time import monotonic

from flow_runner.domain.errors import Cancelled


class CancellationToken:
    def __init__(self, *, clock: Callable[[], float] = monotonic) -> None:
        self._clock = clock
        self._cancelled = asyncio.Event()
        self._active = asyncio.Event()
        self._active.set()
        self._paused = asyncio.Event()
        self._paused_at: float | None = None
        self._paused_total = 0.0

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled.is_set()

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()

    def cancel(self) -> None:
        self._cancelled.set()
        self._active.set()

    def pause(self) -> None:
        if self.is_cancelled or self.is_paused:
            return
        self._paused_at = self._clock()
        self._paused.set()
        self._active.clear()

    def resume(self) -> None:
        if not self.is_paused:
            return
        now = self._clock()
        assert self._paused_at is not None
        self._paused_total += max(0.0, now - self._paused_at)
        self._paused_at = None
        self._paused.clear()
        self._active.set()

    def active_time(self) -> float:
        now = self._clock()
        paused_now = max(0.0, now - self._paused_at) if self._paused_at is not None else 0.0
        return now - self._paused_total - paused_now

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise Cancelled("execution cancelled")

    async def wait_cancelled(self) -> None:
        await self._cancelled.wait()

    async def wait_until_active(self) -> None:
        self.raise_if_cancelled()
        if self._active.is_set():
            return
        active_task = asyncio.create_task(self._active.wait())
        cancel_task = asyncio.create_task(self._cancelled.wait())
        tasks = {active_task, cancel_task}
        try:
            done, _ = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        if cancel_task in done:
            self.raise_if_cancelled()

    async def sleep(self, seconds: float) -> None:
        remaining = max(0.0, seconds)
        while True:
            await self.wait_until_active()
            if remaining <= 0:
                await asyncio.sleep(0)
                await self.wait_until_active()
                return
            started_at = self.active_time()
            timer_task = asyncio.create_task(asyncio.sleep(remaining))
            pause_task = asyncio.create_task(self._paused.wait())
            cancel_task = asyncio.create_task(self._cancelled.wait())
            tasks = {timer_task, pause_task, cancel_task}
            try:
                done, _ = await asyncio.wait(
                    tasks,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            finally:
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
            if cancel_task in done:
                self.raise_if_cancelled()
            if pause_task in done:
                remaining = max(0.0, remaining - (self.active_time() - started_at))
                continue
            if timer_task in done:
                return

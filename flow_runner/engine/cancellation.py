import asyncio

from flow_runner.domain.errors import Cancelled


class CancellationToken:
    def __init__(self) -> None:
        self._event = asyncio.Event()

    @property
    def is_cancelled(self) -> bool:
        return self._event.is_set()

    def cancel(self) -> None:
        self._event.set()

    def raise_if_cancelled(self) -> None:
        if self.is_cancelled:
            raise Cancelled("execution cancelled")

    async def wait_cancelled(self) -> None:
        await self._event.wait()

    async def sleep(self, seconds: float) -> None:
        self.raise_if_cancelled()
        if seconds <= 0:
            await asyncio.sleep(0)
            self.raise_if_cancelled()
            return
        try:
            await asyncio.wait_for(self._event.wait(), timeout=seconds)
        except TimeoutError:
            return
        raise Cancelled("execution cancelled")

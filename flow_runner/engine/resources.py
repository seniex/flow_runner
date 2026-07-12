from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
from typing import Protocol, TypeVar

from flow_runner.engine.perception import PerceptionService


class SceneBoundResult(Protocol):
    scene_generation: int


ResultT = TypeVar("ResultT", bound=SceneBoundResult)
ActionReturnT = TypeVar("ActionReturnT")


class _AsyncReadWriteLock:
    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._readers = 0
        self._writer = False
        self._waiting_writers = 0

    @asynccontextmanager
    async def read(self) -> AsyncIterator[None]:
        async with self._condition:
            await self._condition.wait_for(lambda: not self._writer and self._waiting_writers == 0)
            self._readers += 1
        try:
            yield
        finally:
            async with self._condition:
                self._readers -= 1
                if self._readers == 0:
                    self._condition.notify_all()

    @asynccontextmanager
    async def write(self) -> AsyncIterator[None]:
        async with self._condition:
            self._waiting_writers += 1
            try:
                await self._condition.wait_for(lambda: not self._writer and self._readers == 0)
                self._writer = True
            finally:
                self._waiting_writers -= 1
        try:
            yield
        finally:
            async with self._condition:
                self._writer = False
                self._condition.notify_all()


class ResourceCoordinator:
    def __init__(self, perception: PerceptionService | None = None) -> None:
        self.perception = perception
        self._desktop_hierarchy = _AsyncReadWriteLock()
        self._targets: dict[str, _AsyncReadWriteLock] = {}
        self._exclusive_resources: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def observe(self, target: str) -> AsyncIterator[None]:
        async with self._target_lock(target).read():
            yield

    @asynccontextmanager
    async def interact(
        self,
        target: str,
        *,
        resources: Iterable[str] = (),
    ) -> AsyncIterator[None]:
        hierarchy_lease = (
            self._desktop_hierarchy.write()
            if target == "desktop"
            else self._desktop_hierarchy.read()
        )
        named_locks = [self._resource_lock(name) for name in sorted(set(resources))]
        async with hierarchy_lease:
            async with self._target_lock(target).write():
                for lock in named_locks:
                    await lock.acquire()
                try:
                    yield
                finally:
                    for lock in reversed(named_locks):
                        lock.release()

    async def execute_with_fresh_result(
        self,
        target: str,
        result: ResultT,
        *,
        action: Callable[[ResultT], Awaitable[ActionReturnT]],
        revalidate: Callable[[], Awaitable[ResultT]],
        resources: Iterable[str] = (),
    ) -> ActionReturnT:
        if self.perception is None:
            raise RuntimeError("fresh-result execution requires a perception service")
        async with self.interact(target, resources=resources):
            current = result
            if current.scene_generation != self.perception.current_generation(target):
                current = await revalidate()
            try:
                return await action(current)
            finally:
                self.perception.mark_scene_changed(target)

    def _target_lock(self, target: str) -> _AsyncReadWriteLock:
        return self._targets.setdefault(target, _AsyncReadWriteLock())

    def _resource_lock(self, name: str) -> asyncio.Lock:
        return self._exclusive_resources.setdefault(name, asyncio.Lock())

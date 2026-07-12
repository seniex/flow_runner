from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import monotonic
from typing import Protocol, TypeVar

from flow_runner.engine.perception import PerceptionService


class SceneBoundResult(Protocol):
    scene_generation: int


ResultT = TypeVar("ResultT", bound=SceneBoundResult)
ActionReturnT = TypeVar("ActionReturnT")
ResourceEventSink = Callable[["ResourceEvent"], None]


@dataclass(frozen=True, slots=True)
class ResourceEvent:
    kind: str
    target: str
    mode: str
    resources: tuple[str, ...]
    wait_seconds: float | None = None


class _AsyncReadWriteLock:
    def __init__(self) -> None:
        self._condition = asyncio.Condition()
        self._readers = 0
        self._writer = False
        self._waiting_writers = 0

    @property
    def read_would_wait(self) -> bool:
        return self._writer or self._waiting_writers > 0

    @property
    def write_would_wait(self) -> bool:
        return self._writer or self._readers > 0

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
    def __init__(
        self,
        perception: PerceptionService | None = None,
        *,
        event_sink: ResourceEventSink | None = None,
    ) -> None:
        self.perception = perception
        self.event_sink = event_sink
        self._desktop_hierarchy = _AsyncReadWriteLock()
        self._targets: dict[str, _AsyncReadWriteLock] = {}
        self._exclusive_resources: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def observe(self, target: str) -> AsyncIterator[None]:
        target_lock = self._target_lock(target)
        waiting = target_lock.read_would_wait
        started_at = self._begin_wait(target, "observe", (target,)) if waiting else None
        acquired = False
        try:
            async with target_lock.read():
                acquired = True
                self._finish_wait(target, "observe", (target,), started_at)
                yield
        except BaseException:
            if not acquired:
                self._cancel_wait(target, "observe", (target,), started_at)
            raise

    @asynccontextmanager
    async def interact(
        self,
        target: str,
        *,
        resources: Iterable[str] = (),
    ) -> AsyncIterator[None]:
        resource_names = tuple(sorted(set(resources)))
        diagnostic_resources = (*resource_names, target)
        target_lock = self._target_lock(target)
        hierarchy_waiting = (
            self._desktop_hierarchy.write_would_wait
            if target == "desktop"
            else self._desktop_hierarchy.read_would_wait
        )
        named_locks = [self._resource_lock(name) for name in resource_names]
        waiting = (
            hierarchy_waiting
            or target_lock.write_would_wait
            or any(lock.locked() for lock in named_locks)
        )
        started_at = (
            self._begin_wait(target, "interact", diagnostic_resources) if waiting else None
        )
        hierarchy_lease = (
            self._desktop_hierarchy.write()
            if target == "desktop"
            else self._desktop_hierarchy.read()
        )
        acquired: list[asyncio.Lock] = []
        acquisition_complete = False
        try:
            async with hierarchy_lease:
                async with target_lock.write():
                    try:
                        for lock in named_locks:
                            await lock.acquire()
                            acquired.append(lock)
                    except BaseException:
                        for lock in reversed(acquired):
                            lock.release()
                        raise
                    try:
                        acquisition_complete = True
                        self._finish_wait(
                            target,
                            "interact",
                            diagnostic_resources,
                            started_at,
                        )
                        yield
                    finally:
                        for lock in reversed(acquired):
                            lock.release()
        except BaseException:
            if not acquisition_complete:
                self._cancel_wait(
                    target,
                    "interact",
                    diagnostic_resources,
                    started_at,
                )
            raise

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

    def _begin_wait(self, target: str, mode: str, resources: tuple[str, ...]) -> float:
        started_at = monotonic()
        self._emit(
            ResourceEvent(
                kind="resource.wait.started",
                target=target,
                mode=mode,
                resources=resources,
            )
        )
        return started_at

    def _finish_wait(
        self,
        target: str,
        mode: str,
        resources: tuple[str, ...],
        started_at: float | None,
    ) -> None:
        if started_at is None:
            return
        self._emit(
            ResourceEvent(
                kind="resource.wait.finished",
                target=target,
                mode=mode,
                resources=resources,
                wait_seconds=monotonic() - started_at,
            )
        )

    def _cancel_wait(
        self,
        target: str,
        mode: str,
        resources: tuple[str, ...],
        started_at: float | None,
    ) -> None:
        if started_at is None:
            return
        self._emit(
            ResourceEvent(
                kind="resource.wait.cancelled",
                target=target,
                mode=mode,
                resources=resources,
                wait_seconds=monotonic() - started_at,
            )
        )

    def _emit(self, event: ResourceEvent) -> None:
        if self.event_sink is not None:
            self.event_sink(event)

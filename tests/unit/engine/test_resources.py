import asyncio
from contextlib import suppress
from dataclasses import dataclass

import pytest

from flow_runner.engine.perception import PerceptionService
from flow_runner.engine.resources import ResourceCoordinator


class FakeCapture:
    async def capture(self, target):
        raise AssertionError("capture is not used by these tests")


@pytest.mark.asyncio
async def test_observation_leases_for_same_target_overlap():
    coordinator = ResourceCoordinator()
    entered = 0
    both_entered = asyncio.Event()
    release = asyncio.Event()

    async def observe():
        nonlocal entered
        async with coordinator.observe("window:game"):
            entered += 1
            if entered == 2:
                both_entered.set()
            await release.wait()

    tasks = [asyncio.create_task(observe()), asyncio.create_task(observe())]
    await asyncio.wait_for(both_entered.wait(), timeout=1)
    release.set()
    await asyncio.gather(*tasks)

    assert entered == 2


@pytest.mark.asyncio
async def test_same_target_interactions_are_serialized():
    coordinator = ResourceCoordinator()
    order = []
    first_entered = asyncio.Event()
    release_first = asyncio.Event()

    async def first():
        async with coordinator.interact("window:game"):
            order.append("first-enter")
            first_entered.set()
            await release_first.wait()
            order.append("first-exit")

    async def second():
        await first_entered.wait()
        async with coordinator.interact("window:game"):
            order.append("second-enter")

    tasks = [asyncio.create_task(first()), asyncio.create_task(second())]
    await first_entered.wait()
    await asyncio.sleep(0)
    assert order == ["first-enter"]
    release_first.set()
    await asyncio.gather(*tasks)

    assert order == ["first-enter", "first-exit", "second-enter"]


@pytest.mark.asyncio
async def test_foreground_and_background_modes_share_the_same_window_lock():
    coordinator = ResourceCoordinator()
    active = 0
    peak = 0

    async def use(target):
        nonlocal active, peak
        async with coordinator.interact(target):
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1

    await asyncio.gather(
        use("window:foreground:Game"),
        use("window:background:Game"),
    )

    assert peak == 1


@pytest.mark.asyncio
async def test_contended_interaction_emits_wait_started_and_finished_events():
    events = []
    coordinator = ResourceCoordinator(event_sink=events.append)
    first_entered = asyncio.Event()
    release_first = asyncio.Event()

    async def first():
        async with coordinator.interact("window:game", resources={"mouse"}):
            first_entered.set()
            await release_first.wait()

    async def second():
        await first_entered.wait()
        async with coordinator.interact("window:game", resources={"mouse"}):
            pass

    first_task = asyncio.create_task(first())
    await first_entered.wait()
    second_task = asyncio.create_task(second())
    await asyncio.wait_for(
        _wait_until(lambda: any(event.kind == "resource.wait.started" for event in events)),
        timeout=1,
    )
    release_first.set()
    await asyncio.gather(first_task, second_task)

    assert [event.kind for event in events] == [
        "resource.wait.started",
        "resource.wait.finished",
    ]
    assert events[0].target == "window:game"
    assert events[0].mode == "interact"
    assert events[0].resources == ("mouse", "window:game")
    assert events[1].wait_seconds is not None
    assert events[1].wait_seconds >= 0


@pytest.mark.asyncio
async def test_cancelled_multi_resource_wait_releases_partial_leases():
    events = []
    coordinator = ResourceCoordinator(event_sink=events.append)
    blocker_entered = asyncio.Event()
    release_blocker = asyncio.Event()

    async def blocker():
        async with coordinator.interact("window:blocker", resources={"z"}):
            blocker_entered.set()
            await release_blocker.wait()

    blocker_task = asyncio.create_task(blocker())
    await blocker_entered.wait()
    contender = asyncio.create_task(_hold_resources(coordinator, "window:contender", {"a", "z"}))
    await asyncio.wait_for(
        _wait_until(lambda: any(event.kind == "resource.wait.started" for event in events)),
        timeout=1,
    )

    contender.cancel()
    with suppress(asyncio.CancelledError):
        await contender
    await asyncio.wait_for(
        _hold_resources(coordinator, "window:probe", {"a"}),
        timeout=1,
    )
    release_blocker.set()
    await blocker_task

    assert events[-1].kind == "resource.wait.cancelled"


@pytest.mark.asyncio
async def test_desktop_interaction_blocks_window_interaction():
    coordinator = ResourceCoordinator()
    desktop_entered = asyncio.Event()
    release_desktop = asyncio.Event()
    window_entered = asyncio.Event()

    async def desktop():
        async with coordinator.interact("desktop"):
            desktop_entered.set()
            await release_desktop.wait()

    async def window():
        await desktop_entered.wait()
        async with coordinator.interact("window:game"):
            window_entered.set()

    tasks = [asyncio.create_task(desktop()), asyncio.create_task(window())]
    await desktop_entered.wait()
    await asyncio.sleep(0)
    assert not window_entered.is_set()
    release_desktop.set()
    await asyncio.gather(*tasks)
    assert window_entered.is_set()


@pytest.mark.asyncio
async def test_desktop_interaction_blocks_window_observation():
    coordinator = ResourceCoordinator()
    desktop_entered = asyncio.Event()
    release_desktop = asyncio.Event()
    observation_entered = asyncio.Event()

    async def desktop():
        async with coordinator.interact("desktop"):
            desktop_entered.set()
            await release_desktop.wait()

    async def observe_window():
        await desktop_entered.wait()
        async with coordinator.observe("window:game"):
            observation_entered.set()

    tasks = [asyncio.create_task(desktop()), asyncio.create_task(observe_window())]
    await desktop_entered.wait()
    await asyncio.sleep(0)
    assert not observation_entered.is_set()
    release_desktop.set()
    await asyncio.gather(*tasks)
    assert observation_entered.is_set()


@dataclass(frozen=True)
class PositionedResult:
    scene_generation: int
    position: tuple[int, int]


@pytest.mark.asyncio
async def test_stale_result_is_revalidated_under_interaction_lease():
    perception = PerceptionService(FakeCapture())
    coordinator = ResourceCoordinator(perception)
    perception.mark_scene_changed("window:game")
    revalidation_calls = 0

    async def revalidate():
        nonlocal revalidation_calls
        revalidation_calls += 1
        return PositionedResult(scene_generation=1, position=(20, 30))

    async def action(result):
        return result.position

    position = await coordinator.execute_with_fresh_result(
        "window:game",
        PositionedResult(scene_generation=0, position=(1, 2)),
        action=action,
        revalidate=revalidate,
        resources={"mouse"},
    )

    assert position == (20, 30)
    assert revalidation_calls == 1
    assert perception.current_generation("window:game") == 2


async def _wait_until(predicate):
    while not predicate():
        await asyncio.sleep(0)


async def _hold_resources(coordinator, target, resources):
    async with coordinator.interact(target, resources=resources):
        pass

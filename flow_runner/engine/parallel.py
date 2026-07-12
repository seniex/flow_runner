import asyncio
from collections.abc import Callable, Coroutine, Sequence
from typing import Any

from flow_runner.engine.context import TaskContext, WorkflowContext

ChildCallable = Callable[[], Coroutine[Any, Any, Any]]


class ParallelMonitorGroup:
    def __init__(self, task: TaskContext) -> None:
        self.task = task

    def child_context(self) -> WorkflowContext:
        child_task = TaskContext(
            task_variables=self.task.task_variables,
            persistent_variables=self.task.persistent_variables,
            call_stack=[],
        )
        return WorkflowContext(task=child_task)

    async def run(self, children: Sequence[ChildCallable]) -> list[Any]:
        tasks: list[asyncio.Task[Any]] = [asyncio.create_task(child()) for child in children]
        try:
            return list(await asyncio.gather(*tasks))
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise

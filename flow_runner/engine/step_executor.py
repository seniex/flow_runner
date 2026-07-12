from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from io import BytesIO
from time import monotonic
from typing import Any, cast

from flow_runner.capabilities.registry import CapabilityRegistry
from flow_runner.domain.actions import ActionSpec
from flow_runner.domain.conditions import ConditionGroup, ConditionNode, LeafCondition
from flow_runner.domain.enums import ConditionMode, ConditionOutcome, StepOutcome
from flow_runner.domain.errors import Cancelled
from flow_runner.domain.project import AutomationStep
from flow_runner.domain.results import ActionResult, ConditionResult, StepResult
from flow_runner.engine.bindings import resolve_binding
from flow_runner.engine.cancellation import CancellationToken
from flow_runner.engine.context import StepContext, WorkflowContext
from flow_runner.engine.resources import ResourceCoordinator

SleepCallable = Callable[[float], Awaitable[None]]
ClockCallable = Callable[[], float]


@dataclass(slots=True)
class StepRuntime:
    registry: CapabilityRegistry
    context: StepContext
    cancellation: CancellationToken
    sleep: SleepCallable | None = None
    clock: ClockCallable = monotonic
    resources: ResourceCoordinator | None = None
    activation_gate: Callable[[], Awaitable[None]] | None = None

    def __post_init__(self) -> None:
        if self.sleep is None:
            self.sleep = self.cancellation.sleep

    async def wait(self, seconds: float) -> None:
        if self.sleep is None:
            raise RuntimeError("step runtime sleep callable was not initialized")
        await self.sleep(seconds)
        await self.wait_until_active()

    async def wait_until_active(self) -> None:
        self.cancellation.raise_if_cancelled()
        if self.activation_gate is not None:
            await self.activation_gate()
        self.cancellation.raise_if_cancelled()


class StepExecutor:
    def __init__(self, runtime: StepRuntime) -> None:
        self.runtime = runtime

    def bind_workflow_context(self, context: WorkflowContext) -> None:
        self.runtime.context = StepContext.from_workflow(context)

    def bind_execution_gate(self, gate: Callable[[], Awaitable[None]]) -> None:
        self.runtime.activation_gate = gate

    async def preview_condition(self, step: AutomationStep) -> ConditionResult:
        if step.condition is None:
            raise ValueError("condition preview requires a step condition")
        try:
            await self.runtime.wait_until_active()
            result = await self._evaluate_condition(step.condition)
            self.runtime.context.result = result
            return result
        finally:
            self.runtime.context.clear_result()

    def diagnostic_capture_base64(self, result: ConditionResult) -> str | None:
        coordinator = self.runtime.resources
        if coordinator is None or coordinator.perception is None:
            return None
        frame_id = _first_frame_id(result)
        if frame_id is None:
            return None
        snapshot = coordinator.perception.snapshot_by_frame(frame_id)
        if snapshot is None:
            return None
        output = BytesIO()
        snapshot.image.save(output, format="PNG")
        return base64.b64encode(output.getvalue()).decode("ascii")

    async def execute(self, step: AutomationStep) -> StepResult:
        try:
            await self.runtime.wait_until_active()
            if not step.enabled:
                return StepResult(outcome=StepOutcome.SUCCESS)
            condition = step.condition
            if condition is None:
                action_results, succeeded = await self._execute_actions(
                    step.actions,
                    step.action_policy.max_attempts,
                    step.action_policy.retry_interval_seconds,
                )
                return StepResult(
                    outcome=StepOutcome.SUCCESS if succeeded else StepOutcome.FAILURE,
                    action_results=action_results,
                )
            return await self._execute_condition_step(step, condition)
        except Cancelled as error:
            return StepResult(outcome=StepOutcome.CANCELLED, error=str(error))
        finally:
            self.runtime.context.clear_result()

    async def _execute_condition_step(
        self,
        step: AutomationStep,
        condition: ConditionNode,
    ) -> StepResult:
        policy = step.condition_policy
        started_at = self.runtime.clock()
        attempt = 0
        last_result: ConditionResult | None = None

        while True:
            await self.runtime.wait_until_active()
            self.runtime.context.clear_result()
            hook_results, hooks_succeeded = await self._execute_actions(
                policy.before_attempt_actions,
                step.action_policy.max_attempts,
                step.action_policy.retry_interval_seconds,
            )
            if not hooks_succeeded:
                return StepResult(
                    outcome=StepOutcome.FAILURE,
                    action_results=hook_results,
                    error="before-attempt action failed",
                    condition_attempts=attempt,
                )

            attempt += 1
            last_result = await self._evaluate_condition(condition)
            self.runtime.context.result = last_result
            await self.runtime.wait_until_active()

            if last_result.outcome is ConditionOutcome.MATCH:
                action_results, succeeded = await self._execute_actions(
                    step.actions,
                    step.action_policy.max_attempts,
                    step.action_policy.retry_interval_seconds,
                    revalidate_condition=condition,
                )
                return StepResult(
                    outcome=StepOutcome.SUCCESS if succeeded else StepOutcome.FAILURE,
                    condition_result=self.runtime.context.result or last_result,
                    action_results=action_results,
                    condition_attempts=attempt,
                )

            if last_result.outcome is ConditionOutcome.NO_MATCH:
                hook_results, hooks_succeeded = await self._execute_actions(
                    policy.after_no_match_actions,
                    step.action_policy.max_attempts,
                    step.action_policy.retry_interval_seconds,
                )
                if not hooks_succeeded:
                    return StepResult(
                        outcome=StepOutcome.FAILURE,
                        condition_result=last_result,
                        action_results=hook_results,
                        error="after-no-match action failed",
                        condition_attempts=attempt,
                    )
                if policy.mode is ConditionMode.ONCE:
                    return StepResult(
                        outcome=StepOutcome.NOT_MATCHED,
                        condition_result=last_result,
                        action_results=hook_results,
                        condition_attempts=attempt,
                    )
                terminal_outcome = StepOutcome.TIMEOUT
            else:
                terminal_outcome = StepOutcome.FAILURE

            if self._attempts_exhausted(step, attempt) or self._timeout_reached(step, started_at):
                return StepResult(
                    outcome=terminal_outcome,
                    condition_result=last_result,
                    condition_attempts=attempt,
                )

            await self.runtime.wait(policy.interval_seconds)

    def _attempts_exhausted(self, step: AutomationStep, attempt: int) -> bool:
        maximum = step.condition_policy.max_attempts
        return maximum is not None and attempt >= maximum

    def _timeout_reached(self, step: AutomationStep, started_at: float) -> bool:
        timeout = step.condition_policy.timeout_seconds
        return timeout is not None and self.runtime.clock() - started_at >= timeout

    async def _evaluate_condition(
        self,
        condition: ConditionNode,
        *,
        acquire_resources: bool = True,
    ) -> ConditionResult:
        coordinator = self.runtime.resources
        perception = coordinator.perception if coordinator is not None else None
        if perception is not None:
            async with perception.evaluation_tick():
                return await self._evaluate_condition_node(
                    condition,
                    acquire_resources=acquire_resources,
                )
        return await self._evaluate_condition_node(
            condition,
            acquire_resources=acquire_resources,
        )

    async def _evaluate_condition_node(
        self,
        condition: ConditionNode,
        *,
        acquire_resources: bool,
    ) -> ConditionResult:
        await self.runtime.wait_until_active()
        if isinstance(condition, LeafCondition):
            try:
                provider = self.runtime.registry.condition(condition.capability)
                config = provider.config_model.model_validate(condition.config)
                async with AsyncExitStack() as stack:
                    if acquire_resources and self.runtime.resources is not None:
                        required = provider.required_resources(config)
                        targets = [
                            resource.removeprefix("observe:")
                            for resource in required
                            if resource.startswith("observe:")
                        ]
                        for target in sorted(targets):
                            await stack.enter_async_context(
                                _cancellable_context(
                                    self.runtime.resources.observe(target),
                                    self.runtime.cancellation,
                                )
                            )
                    self.runtime.cancellation.raise_if_cancelled()
                    result = cast(
                        ConditionResult,
                        await provider.evaluate(config, self.runtime.context),
                    )
            except Cancelled:
                raise
            except Exception as error:
                return ConditionResult(
                    node_id=condition.id,
                    outcome=ConditionOutcome.ERROR,
                    provider_data={"error": str(error)},
                )
            if result.node_id != condition.id:
                return result.model_copy(update={"node_id": condition.id})
            return result

        children = [
            await self._evaluate_condition_node(child, acquire_resources=acquire_resources)
            for child in condition.children
        ]
        return self._combine_group(condition, children)

    @staticmethod
    def _combine_group(
        condition: ConditionGroup,
        children: list[ConditionResult],
    ) -> ConditionResult:
        if condition.operator == "and":
            return ConditionResult.and_group(condition.id, children)
        if condition.operator == "or":
            return ConditionResult.or_group(condition.id, children)
        return ConditionResult.not_group(condition.id, children[0])

    async def _execute_actions(
        self,
        actions: list[ActionSpec],
        max_attempts: int,
        retry_interval_seconds: float,
        *,
        revalidate_condition: ConditionNode | None = None,
    ) -> tuple[tuple[ActionResult, ...], bool]:
        completed: list[ActionResult] = []
        for action in actions:
            final_result: ActionResult | None = None
            for attempt in range(1, max_attempts + 1):
                await self.runtime.wait_until_active()
                attempt_result = await self._execute_action(
                    action,
                    revalidate_condition=revalidate_condition,
                )
                final_result = attempt_result.model_copy(update={"attempts": attempt})
                if final_result.outcome is StepOutcome.SUCCESS:
                    break
                if attempt < max_attempts:
                    await self.runtime.wait(retry_interval_seconds)
            if final_result is None:
                raise RuntimeError("action retry loop did not execute")
            completed.append(final_result)
            if final_result.outcome is not StepOutcome.SUCCESS:
                return tuple(completed), False
        return tuple(completed), True

    async def _execute_action(
        self,
        action: ActionSpec,
        *,
        revalidate_condition: ConditionNode | None = None,
    ) -> ActionResult:
        try:
            provider = self.runtime.registry.action(action.capability)
            resolved_config = _resolve_config(action.config, self.runtime.context)
            config = provider.config_model.model_validate(resolved_config)
            required = provider.required_resources(config)
            if self.runtime.resources is None or not required:
                return await self._execute_provider_action(
                    provider,
                    config,
                )
            window_targets = sorted(
                resource for resource in required if resource.startswith("window:")
            )
            scene_target = (
                _single_scene_target(self.runtime.context.result)
                if bool(getattr(provider, "binds_to_scene", False))
                else None
            )
            target = window_targets[0] if window_targets else scene_target or "desktop"
            named_resources = required.difference(window_targets)
            async with _cancellable_context(
                self.runtime.resources.interact(
                    target,
                    resources=named_resources,
                ),
                self.runtime.cancellation,
            ):
                self.runtime.cancellation.raise_if_cancelled()
                if not await self._refresh_stale_condition(
                    revalidate_condition,
                    target,
                ):
                    return ActionResult(
                        outcome=StepOutcome.FAILURE,
                        error="screen result no longer matches after stale revalidation",
                    )
                resolved_config = _resolve_config(action.config, self.runtime.context)
                config = provider.config_model.model_validate(resolved_config)
                try:
                    return await self._execute_provider_action(
                        provider,
                        config,
                    )
                finally:
                    perception = self.runtime.resources.perception
                    if perception is not None:
                        perception.mark_scene_changed(target)
        except Cancelled:
            raise
        except Exception as error:
            return ActionResult(outcome=StepOutcome.FAILURE, error=str(error))

    async def _execute_provider_action(self, provider: Any, config: Any) -> ActionResult:
        action_task = asyncio.create_task(provider.execute(config, self.runtime.context))
        cancel_task = asyncio.create_task(self.runtime.cancellation.wait_cancelled())
        try:
            done, _ = await asyncio.wait(
                {action_task, cancel_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if cancel_task in done:
                self.runtime.cancellation.raise_if_cancelled()
            return cast(ActionResult, action_task.result())
        finally:
            for task in (action_task, cancel_task):
                if not task.done():
                    task.cancel()
            await asyncio.gather(action_task, cancel_task, return_exceptions=True)

    async def _refresh_stale_condition(
        self,
        condition: ConditionNode | None,
        target: str,
    ) -> bool:
        coordinator = self.runtime.resources
        result = self.runtime.context.result
        if condition is None or coordinator is None or coordinator.perception is None:
            return True
        generations = _scene_generations(result, target)
        if not generations:
            return True
        if coordinator.perception.current_generation(target) in generations:
            return True
        fresh = await self._evaluate_condition(condition, acquire_resources=False)
        self.runtime.context.result = fresh
        return fresh.outcome is ConditionOutcome.MATCH


def _resolve_config(value: Any, context: StepContext) -> Any:
    if isinstance(value, str) and value.startswith("$"):
        return resolve_binding(value, context)
    if isinstance(value, dict):
        return {key: _resolve_config(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_config(item, context) for item in value]
    if isinstance(value, tuple):
        return tuple(_resolve_config(item, context) for item in value)
    return value


def _single_scene_target(result: ConditionResult | None) -> str | None:
    targets = _scene_targets(result)
    return next(iter(targets)) if len(targets) == 1 else None


def _scene_targets(result: ConditionResult | None) -> set[str]:
    if result is None:
        return set()
    targets = {result.target} if result.target is not None else set()
    for child in result.children.values():
        targets.update(_scene_targets(child))
    return targets


def _first_frame_id(result: ConditionResult | None) -> str | None:
    if result is None:
        return None
    if result.frame_id is not None:
        return result.frame_id
    for child in result.children.values():
        frame_id = _first_frame_id(child)
        if frame_id is not None:
            return frame_id
    return None


def _scene_generations(result: ConditionResult | None, target: str) -> set[int]:
    if result is None:
        return set()
    generations = (
        {result.scene_generation}
        if result.target == target and result.scene_generation is not None
        else set()
    )
    for child in result.children.values():
        generations.update(_scene_generations(child, target))
    return generations


@asynccontextmanager
async def _cancellable_context(
    manager: AbstractAsyncContextManager[Any],
    cancellation: CancellationToken,
) -> AsyncIterator[Any]:
    stack = AsyncExitStack()
    enter_task = asyncio.create_task(stack.enter_async_context(manager))
    cancel_task = asyncio.create_task(cancellation.wait_cancelled())
    done, pending = await asyncio.wait(
        {enter_task, cancel_task},
        return_when=asyncio.FIRST_COMPLETED,
    )
    if cancel_task in done:
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        await stack.aclose()
        cancellation.raise_if_cancelled()
    cancel_task.cancel()
    await asyncio.gather(cancel_task, return_exceptions=True)
    value = enter_task.result()
    try:
        yield value
    finally:
        await stack.aclose()

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any

from flow_runner.capabilities.registry import CapabilityRegistry
from flow_runner.domain.actions import ActionSpec
from flow_runner.domain.conditions import ConditionGroup, ConditionNode, LeafCondition
from flow_runner.domain.enums import ConditionMode, ConditionOutcome, StepOutcome
from flow_runner.domain.errors import Cancelled
from flow_runner.domain.project import AutomationStep
from flow_runner.domain.results import ActionResult, ConditionResult, StepResult
from flow_runner.engine.bindings import resolve_binding
from flow_runner.engine.cancellation import CancellationToken
from flow_runner.engine.context import StepContext

SleepCallable = Callable[[float], Awaitable[None]]
ClockCallable = Callable[[], float]


@dataclass(slots=True)
class StepRuntime:
    registry: CapabilityRegistry
    context: StepContext
    cancellation: CancellationToken
    sleep: SleepCallable | None = None
    clock: ClockCallable = monotonic

    def __post_init__(self) -> None:
        if self.sleep is None:
            self.sleep = self.cancellation.sleep

    async def wait(self, seconds: float) -> None:
        if self.sleep is None:
            raise RuntimeError("step runtime sleep callable was not initialized")
        await self.sleep(seconds)


class StepExecutor:
    def __init__(self, runtime: StepRuntime) -> None:
        self.runtime = runtime

    async def execute(self, step: AutomationStep) -> StepResult:
        try:
            self.runtime.cancellation.raise_if_cancelled()
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
            self.runtime.cancellation.raise_if_cancelled()
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
                )

            attempt += 1
            last_result = await self._evaluate_condition(condition)
            self.runtime.context.result = last_result

            if last_result.outcome is ConditionOutcome.MATCH:
                action_results, succeeded = await self._execute_actions(
                    step.actions,
                    step.action_policy.max_attempts,
                    step.action_policy.retry_interval_seconds,
                )
                return StepResult(
                    outcome=StepOutcome.SUCCESS if succeeded else StepOutcome.FAILURE,
                    condition_result=last_result,
                    action_results=action_results,
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
                    )
                if policy.mode is ConditionMode.ONCE:
                    return StepResult(
                        outcome=StepOutcome.NOT_MATCHED,
                        condition_result=last_result,
                        action_results=hook_results,
                    )
                terminal_outcome = StepOutcome.TIMEOUT
            else:
                terminal_outcome = StepOutcome.FAILURE

            if self._attempts_exhausted(step, attempt) or self._timeout_reached(step, started_at):
                return StepResult(
                    outcome=terminal_outcome,
                    condition_result=last_result,
                )

            await self.runtime.wait(policy.interval_seconds)

    def _attempts_exhausted(self, step: AutomationStep, attempt: int) -> bool:
        maximum = step.condition_policy.max_attempts
        return maximum is not None and attempt >= maximum

    def _timeout_reached(self, step: AutomationStep, started_at: float) -> bool:
        timeout = step.condition_policy.timeout_seconds
        return timeout is not None and self.runtime.clock() - started_at >= timeout

    async def _evaluate_condition(self, condition: ConditionNode) -> ConditionResult:
        if isinstance(condition, LeafCondition):
            provider = self.runtime.registry.condition(condition.capability)
            config = provider.config_model.model_validate(condition.config)
            try:
                result = await provider.evaluate(config, self.runtime.context)
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

        children = [await self._evaluate_condition(child) for child in condition.children]
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
    ) -> tuple[tuple[ActionResult, ...], bool]:
        completed: list[ActionResult] = []
        for action in actions:
            final_result: ActionResult | None = None
            for attempt in range(1, max_attempts + 1):
                self.runtime.cancellation.raise_if_cancelled()
                final_result = await self._execute_action(action)
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

    async def _execute_action(self, action: ActionSpec) -> ActionResult:
        provider = self.runtime.registry.action(action.capability)
        resolved_config = _resolve_config(action.config, self.runtime.context)
        config = provider.config_model.model_validate(resolved_config)
        try:
            return await provider.execute(config, self.runtime.context)
        except Cancelled:
            raise
        except Exception as error:
            return ActionResult(outcome=StepOutcome.FAILURE, error=str(error))


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

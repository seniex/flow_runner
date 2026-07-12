from datetime import datetime
from uuid import uuid4

import pytest

from flow_runner.capabilities.conditions.count import CountCondition, CountConditionConfig
from flow_runner.capabilities.conditions.time import TimeCondition, TimeConditionConfig
from flow_runner.capabilities.conditions.variables import (
    VariableCondition,
    VariableConditionConfig,
)
from flow_runner.domain.enums import ConditionOutcome
from flow_runner.domain.routing import ComparisonOperator
from flow_runner.engine.context import StepContext


@pytest.mark.asyncio
async def test_variable_condition_compares_task_values():
    context = StepContext(task_variables={"level": 12})
    result = await VariableCondition().evaluate(
        VariableConditionConfig(
            scope="task", name="level", operator=ComparisonOperator.GE, expected=10
        ),
        context,
    )
    assert result.outcome is ConditionOutcome.MATCH


@pytest.mark.asyncio
async def test_count_condition_reads_workflow_and_step_counters():
    workflow_id = uuid4()
    step_id = uuid4()
    context = StepContext(workflow_counts={workflow_id: 3}, step_counts={step_id: 7})
    workflow_result = await CountCondition().evaluate(
        CountConditionConfig(counter="workflow", target_id=workflow_id, operator="eq", expected=3),
        context,
    )
    step_result = await CountCondition().evaluate(
        CountConditionConfig(counter="step", target_id=step_id, operator="gt", expected=5),
        context,
    )
    assert workflow_result.outcome is ConditionOutcome.MATCH
    assert step_result.outcome is ConditionOutcome.MATCH


@pytest.mark.asyncio
async def test_elapsed_time_and_midnight_range_are_supported():
    elapsed = TimeCondition(monotonic_clock=lambda: 15.0, now=lambda: datetime(2026, 1, 1, 1, 0))
    elapsed_result = await elapsed.evaluate(
        TimeConditionConfig(mode="elapsed", started_at=10.0, seconds=5.0), StepContext()
    )
    range_result = await elapsed.evaluate(
        TimeConditionConfig(mode="local_range", start="23:00", end="02:00"), StepContext()
    )
    assert elapsed_result.outcome is ConditionOutcome.MATCH
    assert range_result.outcome is ConditionOutcome.MATCH

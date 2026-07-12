import pytest

from flow_runner.capabilities.actions.variables import SetVariableAction, SetVariableConfig
from flow_runner.capabilities.actions.wait import WaitAction, WaitActionConfig
from flow_runner.domain.enums import StepOutcome
from flow_runner.engine.context import StepContext


@pytest.mark.asyncio
async def test_wait_action_uses_injected_cancellable_sleep():
    delays = []

    async def sleep(seconds):
        delays.append(seconds)

    result = await WaitAction(sleep).execute(WaitActionConfig(seconds=1.25), StepContext())

    assert result.outcome is StepOutcome.SUCCESS
    assert delays == [1.25]


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", ["task", "workflow", "persistent"])
async def test_set_variable_action_writes_the_selected_scope(scope):
    context = StepContext()
    action = SetVariableAction()

    result = await action.execute(SetVariableConfig(scope=scope, name="counter", value=3), context)

    assert result.outcome is StepOutcome.SUCCESS
    assert getattr(context, f"{scope}_variables")["counter"] == 3


def test_wait_and_variable_actions_declare_no_desktop_resources():
    assert (
        WaitAction(lambda seconds: None).required_resources(WaitActionConfig(seconds=0))
        == frozenset()
    )
    assert (
        SetVariableAction().required_resources(SetVariableConfig(scope="task", name="x", value=1))
        == frozenset()
    )

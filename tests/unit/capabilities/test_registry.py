import pytest
from pydantic import BaseModel, Field

from flow_runner.capabilities.registry import CapabilityRegistry
from flow_runner.domain.actions import ActionSpec
from flow_runner.domain.conditions import ConditionGroup, LeafCondition
from flow_runner.domain.errors import ConfigurationError
from flow_runner.domain.policies import ConditionPolicy
from flow_runner.domain.project import AutomationStep, FlowGroup, Project, Workflow


class EmptyConfig(BaseModel):
    pass


class FakeCondition:
    name = "fake.condition"
    config_model = EmptyConfig

    async def evaluate(self, config, context):
        raise NotImplementedError

    def required_resources(self, config):
        return frozenset()


class LaterCondition(FakeCondition):
    name = "later.condition"


class RequiredConfig(BaseModel):
    value: int = Field(gt=0)


class RequiredCondition(FakeCondition):
    name = "required.condition"
    config_model = RequiredConfig


class RequiredAction:
    name = "required.action"
    config_model = RequiredConfig


def test_registry_rejects_duplicate_names():
    registry = CapabilityRegistry()
    registry.register_condition(FakeCondition())

    with pytest.raises(ConfigurationError, match="fake.condition"):
        registry.register_condition(FakeCondition())


def test_registry_reports_unknown_capability():
    registry = CapabilityRegistry()

    with pytest.raises(ConfigurationError, match="missing.condition"):
        registry.condition("missing.condition")


def test_registry_metadata_is_sorted_and_separates_kinds():
    registry = CapabilityRegistry()
    registry.register_condition(LaterCondition())
    registry.register_condition(FakeCondition())

    assert [item.name for item in registry.condition_metadata()] == [
        "fake.condition",
        "later.condition",
    ]
    assert registry.action_metadata() == ()


def test_registry_validates_all_project_capability_configs_with_paths():
    registry = CapabilityRegistry()
    registry.register_condition(RequiredCondition())
    registry.register_action(RequiredAction())
    step = AutomationStep(
        name="invalid",
        condition=ConditionGroup(
            id="all",
            operator="and",
            children=[
                LeafCondition(
                    id="leaf",
                    capability="required.condition",
                    config={},
                )
            ],
        ),
        actions=[ActionSpec(capability="required.action", config={"value": 0})],
        condition_policy=ConditionPolicy(
            before_attempt_actions=[ActionSpec(capability="missing.action", config={})]
        ),
    )
    project = Project(
        name="p",
        groups=[FlowGroup(name="g", workflows=[Workflow(name="w", steps=[step])])],
    )

    errors = registry.validate_project(project)

    assert len(errors) == 3
    assert any("condition.children[0]" in error and "leaf" in error for error in errors)
    assert any("actions[0]" in error and "greater than 0" in error for error in errors)
    assert any(
        "before_attempt_actions[0]" in error and "missing.action" in error for error in errors
    )


def test_registry_accepts_runtime_bindings_while_validating_other_fields():
    registry = CapabilityRegistry()
    registry.register_action(RequiredAction())
    valid = Project(
        name="bound",
        groups=[
            FlowGroup(
                name="g",
                workflows=[
                    Workflow(
                        name="w",
                        steps=[
                            AutomationStep(
                                name="bound action",
                                actions=[
                                    ActionSpec(
                                        capability="required.action",
                                        config={"value": "$variables.task.amount"},
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        ],
    )

    assert registry.validate_project(valid) == []

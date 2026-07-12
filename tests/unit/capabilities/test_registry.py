import pytest
from pydantic import BaseModel

from flow_runner.capabilities.registry import CapabilityRegistry
from flow_runner.domain.errors import ConfigurationError


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

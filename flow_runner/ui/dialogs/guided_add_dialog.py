from typing import Any
from uuid import UUID

from PySide6.QtWidgets import QComboBox, QDialog, QFormLayout

from flow_runner.capabilities.registry import CapabilityRegistry
from flow_runner.domain.actions import ActionSpec
from flow_runner.domain.conditions import LeafCondition
from flow_runner.domain.enums import StepOutcome
from flow_runner.domain.project import AutomationStep
from flow_runner.domain.routing import RouteRule, RouteTarget

CONTROL_CAPABILITIES = (
    ("下一步骤", "next_step"),
    ("跳转流程", "jump_workflow"),
    ("调用流程", "call_workflow"),
    ("返回调用方", "return"),
    ("结束任务", "end"),
)


class GuidedAddDialog(QDialog):
    def __init__(self, registry: CapabilityRegistry) -> None:
        super().__init__()
        self.registry = registry
        self.category_combo = QComboBox()
        self.category_combo.addItems(["检测", "执行", "控制"])
        self.capability_combo = QComboBox()
        self.category_combo.currentTextChanged.connect(self._populate_capabilities)
        self._populate_capabilities(self.category_combo.currentText())
        layout = QFormLayout(self)
        layout.addRow("类别", self.category_combo)
        layout.addRow("能力", self.capability_combo)

    def build_step(
        self,
        *,
        category: str,
        capability: str,
        config: dict[str, Any],
    ) -> AutomationStep:
        if category == "检测":
            provider = self.registry.condition(capability)
            validated = provider.config_model.model_validate(config).model_dump(mode="python")
            return AutomationStep(
                name=capability,
                condition=LeafCondition(
                    id="condition",
                    capability=capability,
                    config=validated,
                ),
            )
        if category == "执行":
            provider = self.registry.action(capability)
            validated = provider.config_model.model_validate(config).model_dump(mode="python")
            return AutomationStep(
                name=capability,
                actions=[ActionSpec(capability=capability, config=validated)],
            )
        if category == "控制":
            outcome = StepOutcome(config.get("outcome", StepOutcome.SUCCESS))
            return AutomationStep(
                name=capability,
                routes=[RouteRule(outcome=outcome, target=_control_target(capability, config))],
            )
        raise ValueError(f"unknown guided category: {category}")

    def _populate_capabilities(self, category: str) -> None:
        self.capability_combo.clear()
        if category == "检测":
            items = [(item.name, item.name) for item in self.registry.condition_metadata()]
        elif category == "执行":
            items = [(item.name, item.name) for item in self.registry.action_metadata()]
        else:
            items = list(CONTROL_CAPABILITIES)
        for label, capability in items:
            self.capability_combo.addItem(label, capability)


def _control_target(capability: str, config: dict[str, Any]) -> RouteTarget:
    if capability == "next_step":
        return RouteTarget.next_step(UUID(str(config["step_id"])))
    if capability == "jump_workflow":
        return RouteTarget.jump_workflow(UUID(str(config["workflow_id"])))
    if capability == "call_workflow":
        return RouteTarget.call_workflow(UUID(str(config["workflow_id"])))
    if capability == "return":
        return RouteTarget.return_to_caller()
    if capability == "end":
        return RouteTarget.end()
    raise ValueError(f"unknown control capability: {capability}")

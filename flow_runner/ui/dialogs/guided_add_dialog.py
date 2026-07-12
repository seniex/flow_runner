from typing import Any

from PySide6.QtWidgets import QComboBox, QDialog, QFormLayout

from flow_runner.capabilities.registry import CapabilityRegistry
from flow_runner.domain.conditions import LeafCondition
from flow_runner.domain.project import AutomationStep


class GuidedAddDialog(QDialog):
    def __init__(self, registry: CapabilityRegistry) -> None:
        super().__init__()
        self.registry = registry
        self.category_combo = QComboBox()
        self.category_combo.addItems(["检测", "执行", "控制"])
        self.capability_combo = QComboBox()
        for metadata in registry.condition_metadata():
            self.capability_combo.addItem(metadata.name, metadata.name)
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
        if category != "检测":
            raise ValueError("this guided builder currently requires a detection category")
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

from typing import Any

from pydantic import BaseModel
from PySide6.QtWidgets import QCheckBox, QComboBox, QLabel, QVBoxLayout, QWidget

from flow_runner.capabilities.registry import CapabilityRegistry
from flow_runner.domain.conditions import ConditionNode, LeafCondition
from flow_runner.domain.project import AutomationStep
from flow_runner.ui.editors.model_form import ModelForm


class ConditionEditor(QWidget):
    def __init__(self, registry: CapabilityRegistry) -> None:
        super().__init__()
        self.registry = registry
        self.enabled_check = QCheckBox("使用条件")
        self.capability_combo = QComboBox()
        for metadata in registry.condition_metadata():
            self.capability_combo.addItem(metadata.name, metadata.name)
        self.form_container = QWidget()
        self.form_layout = QVBoxLayout(self.form_container)
        self.config_form: ModelForm | None = None
        self.message_label = QLabel("")
        self._node_id = "condition"
        self._advanced_condition: ConditionNode | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(self.enabled_check)
        layout.addWidget(self.capability_combo)
        layout.addWidget(self.form_container)
        layout.addWidget(self.message_label)
        self.capability_combo.currentIndexChanged.connect(lambda _: self._switch_form())
        self.enabled_check.toggled.connect(self._update_enabled)
        self._switch_form()
        self._update_enabled(False)

    def set_condition(self, condition: ConditionNode | None) -> None:
        self._advanced_condition = condition
        if condition is None:
            self.enabled_check.setChecked(False)
            self.message_label.clear()
            return
        self.enabled_check.setChecked(True)
        if not isinstance(condition, LeafCondition):
            self.capability_combo.setEnabled(False)
            self.form_container.setEnabled(False)
            self.message_label.setText("复合条件请使用高级 JSON 编辑器")
            return
        self._node_id = condition.id
        self._advanced_condition = None
        self.capability_combo.setEnabled(True)
        self.form_container.setEnabled(True)
        self.message_label.clear()
        index = self.capability_combo.findData(condition.capability)
        if index >= 0:
            self.capability_combo.setCurrentIndex(index)
        self._switch_form(condition.config)

    def condition(self) -> ConditionNode | None:
        if not self.enabled_check.isChecked():
            return None
        if self._advanced_condition is not None:
            return self._advanced_condition
        capability = self.capability_combo.currentData()
        if not isinstance(capability, str) or self.config_form is None:
            raise ValueError("请选择检测能力")
        config = (
            self.registry.condition(capability)
            .config_model.model_validate(self.config_form.values())
            .model_dump(mode="python")
        )
        return LeafCondition(id=self._node_id, capability=capability, config=config)

    def _switch_form(self, values: dict[str, Any] | None = None) -> None:
        previous = values
        if previous is None and self.config_form is not None:
            try:
                previous = self.config_form.values()
            except ValueError:
                previous = {}
        while self.form_layout.count():
            item = self.form_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        capability = self.capability_combo.currentData()
        self.config_form = None
        if not isinstance(capability, str):
            return
        model_type = self.registry.condition(capability).config_model
        self.config_form = ModelForm(model_type)
        if previous:
            allowed = set(model_type.model_fields)
            self.config_form.set_values(
                {name: value for name, value in previous.items() if name in allowed}
            )
        self.form_layout.addWidget(self.config_form)

    def _update_enabled(self, enabled: bool) -> None:
        self.capability_combo.setEnabled(enabled and self._advanced_condition is None)
        self.form_container.setEnabled(enabled and self._advanced_condition is None)


def switch_condition_capability(
    step: AutomationStep,
    capability: str,
    config_model: type[BaseModel],
    *,
    required_config: dict[str, Any] | None = None,
) -> tuple[AutomationStep, dict[str, Any]]:
    condition = step.condition
    if not isinstance(condition, LeafCondition):
        raise ValueError("capability switching requires a leaf condition")
    allowed = set(config_model.model_fields)
    preserved = {key: value for key, value in condition.config.items() if key in allowed}
    discarded = {key: value for key, value in condition.config.items() if key not in allowed}
    preserved.update(required_config or {})
    validated = config_model.model_validate(preserved).model_dump(mode="python")
    replacement = LeafCondition(
        id=condition.id,
        capability=capability,
        config=validated,
    )
    return step.model_copy(update={"condition": replacement}), discarded

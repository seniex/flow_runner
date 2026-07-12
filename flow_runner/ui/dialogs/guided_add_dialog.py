import json
from typing import Any
from uuid import UUID

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from flow_runner.capabilities.registry import CapabilityRegistry
from flow_runner.domain.actions import ActionSpec
from flow_runner.domain.conditions import LeafCondition
from flow_runner.domain.enums import StepOutcome
from flow_runner.domain.project import AutomationStep
from flow_runner.domain.routing import RouteRule, RouteTarget
from flow_runner.ui.editors.model_form import ModelForm

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
        self._step: AutomationStep | None = None
        self.category_combo = QComboBox()
        self.category_combo.addItems(["检测", "执行", "控制"])
        self.capability_combo = QComboBox()
        self.form_container = QWidget()
        self.form_layout = QVBoxLayout(self.form_container)
        self.config_form: ModelForm | None = None
        self.category_combo.currentTextChanged.connect(self._populate_capabilities)
        self.capability_combo.currentIndexChanged.connect(self._rebuild_form)
        self._populate_capabilities(self.category_combo.currentText())
        self.config_edit = QPlainTextEdit("{}")
        self.config_edit.setObjectName("guidedStepConfigEditor")
        self.error_label = QLabel("")
        self.error_label.setObjectName("guidedStepError")
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QFormLayout(self)
        layout.addRow("类别", self.category_combo)
        layout.addRow("能力", self.capability_combo)
        layout.addRow("配置", self.form_container)
        layout.addRow("高级 JSON 覆盖", self.config_edit)
        layout.addRow("", self.error_label)
        layout.addRow(self.buttons)

    def accept(self) -> None:
        try:
            advanced = self.config_edit.toPlainText().strip()
            config = (
                json.loads(advanced)
                if advanced not in {"", "{}"}
                else self.config_form.values()
                if self.config_form is not None
                else {}
            )
            if not isinstance(config, dict):
                raise ValueError("配置必须是 JSON 对象")
            capability = self.capability_combo.currentData()
            if not isinstance(capability, str):
                raise ValueError("请选择能力")
            self._step = self.build_step(
                category=self.category_combo.currentText(),
                capability=capability,
                config=config,
            )
        except (ValueError, KeyError) as error:
            self.error_label.setText(str(error))
            return
        super().accept()

    def step(self) -> AutomationStep:
        if self._step is None:
            raise RuntimeError("guided step dialog has not been accepted")
        return self._step

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
        self._rebuild_form()

    def _rebuild_form(self) -> None:
        while self.form_layout.count():
            item = self.form_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.config_form = None
        category = self.category_combo.currentText()
        capability = self.capability_combo.currentData()
        if not isinstance(capability, str) or category == "控制":
            self.form_container.setVisible(False)
            return
        provider = (
            self.registry.condition(capability)
            if category == "检测"
            else self.registry.action(capability)
        )
        self.config_form = ModelForm(provider.config_model)
        self.form_layout.addWidget(self.config_form)
        self.form_container.setVisible(True)


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

import json
from uuid import UUID

from pydantic import BaseModel
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from flow_runner.domain.project import AutomationStep


class PropertyPanel(QWidget):
    stepChanged = Signal(object)
    validationFailed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("propertyPanel")
        self.step_id: UUID | None = None
        self._step: AutomationStep | None = None
        self.title = QLabel("")
        self.name_edit = QLineEdit()
        self.name_edit.setObjectName("stepNameEditor")
        self.enabled_check = QCheckBox("启用")
        self.enabled_check.setObjectName("stepEnabledEditor")
        self.condition_edit = QPlainTextEdit()
        self.condition_edit.setObjectName("conditionModelEditor")
        self.actions_edit = QPlainTextEdit()
        self.actions_edit.setObjectName("actionsModelEditor")
        self.condition_policy_edit = QPlainTextEdit()
        self.condition_policy_edit.setObjectName("conditionPolicyModelEditor")
        self.action_policy_edit = QPlainTextEdit()
        self.action_policy_edit.setObjectName("actionPolicyModelEditor")
        self.routes_edit = QPlainTextEdit()
        self.routes_edit.setObjectName("routesModelEditor")
        self.apply_button = QPushButton("应用")
        self.apply_button.setObjectName("applyStepButton")
        layout = QVBoxLayout(self)
        layout.addWidget(self.title)
        form = QFormLayout()
        form.addRow("名称", self.name_edit)
        form.addRow("状态", self.enabled_check)
        form.addRow("条件", self.condition_edit)
        form.addRow("动作", self.actions_edit)
        form.addRow("检测策略", self.condition_policy_edit)
        form.addRow("动作策略", self.action_policy_edit)
        form.addRow("路由", self.routes_edit)
        layout.addLayout(form)
        layout.addWidget(self.apply_button)
        layout.addStretch()
        self.apply_button.clicked.connect(self._apply)

    def set_step(self, step: AutomationStep) -> None:
        self.step_id = step.id
        self._step = step
        self.title.setText(step.name)
        self.name_edit.setText(step.name)
        self.enabled_check.setChecked(step.enabled)
        self.condition_edit.setPlainText(_json(step.condition))
        self.actions_edit.setPlainText(_json(step.actions))
        self.condition_policy_edit.setPlainText(_json(step.condition_policy))
        self.action_policy_edit.setPlainText(_json(step.action_policy))
        self.routes_edit.setPlainText(_json(step.routes))

    def _apply(self) -> None:
        if self._step is None:
            return
        try:
            step = AutomationStep.model_validate(
                {
                    "id": self._step.id,
                    "name": self.name_edit.text(),
                    "enabled": self.enabled_check.isChecked(),
                    "condition": json.loads(self.condition_edit.toPlainText()),
                    "actions": json.loads(self.actions_edit.toPlainText()),
                    "condition_policy": json.loads(self.condition_policy_edit.toPlainText()),
                    "action_policy": json.loads(self.action_policy_edit.toPlainText()),
                    "routes": json.loads(self.routes_edit.toPlainText()),
                }
            )
        except ValueError as error:
            self.validationFailed.emit(str(error))
            return
        self.set_step(step)
        self.stepChanged.emit(step)


def _json(value: object) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    elif isinstance(value, list):
        value = [
            item.model_dump(mode="json") if isinstance(item, BaseModel) else item for item in value
        ]
    return json.dumps(value, ensure_ascii=False, indent=2)

from uuid import UUID

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
)

from flow_runner.display_labels import ProjectDisplayIndex
from flow_runner.domain.project import AutomationStep, Project
from flow_runner.ui.step_templates import STEP_TEMPLATES, build_template_step
from flow_runner.ui.widgets import FocusWheelComboBox, FocusWheelDoubleSpinBox


class TemplateStepDialog(QDialog):
    def __init__(self, project: Project, *, current_workflow_id: UUID) -> None:
        super().__init__()
        self.project = project
        self.current_workflow_id = current_workflow_id
        self._step: AutomationStep | None = None
        self.template_combo = FocusWheelComboBox()
        for template_id, template in STEP_TEMPLATES.items():
            self.template_combo.addItem(template.name, template_id)
        self.name_edit = QLineEdit()
        self.keywords_edit = QLineEdit()
        self.seconds_spin = FocusWheelDoubleSpinBox()
        self.seconds_spin.setRange(0.0, 1_000_000.0)
        self.seconds_spin.setValue(1.0)
        self.timeout_spin = FocusWheelDoubleSpinBox()
        self.timeout_spin.setRange(0.1, 1_000_000.0)
        self.timeout_spin.setValue(10.0)
        self.key_edit = QLineEdit()
        self.window_process_name_edit = QLineEdit()
        self.target_step_combo = FocusWheelComboBox()
        self.target_workflow_combo = FocusWheelComboBox()
        self.success_workflow_combo = FocusWheelComboBox()
        self.timeout_workflow_combo = FocusWheelComboBox()
        self.error_label = QLabel()
        self.error_label.setObjectName("templateStepError")
        self.error_label.setWordWrap(True)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.form = QFormLayout(self)
        self.form.addRow("模板", self.template_combo)
        self.form.addRow("步骤名称", self.name_edit)
        self.form.addRow("匹配文字", self.keywords_edit)
        self.form.addRow("等待秒数", self.seconds_spin)
        self.form.addRow("超时秒数", self.timeout_spin)
        self.form.addRow("按键", self.key_edit)
        self.form.addRow("进程名", self.window_process_name_edit)
        self.form.addRow("后续步骤", self.target_step_combo)
        self.form.addRow("目标流程", self.target_workflow_combo)
        self.form.addRow("成功流程", self.success_workflow_combo)
        self.form.addRow("超时流程", self.timeout_workflow_combo)
        self.form.addRow("", self.error_label)
        self.form.addRow(self.buttons)
        self._populate_targets()
        self.template_combo.currentIndexChanged.connect(self._template_changed)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self._template_changed()

    def accept(self) -> None:
        template_id = self.template_combo.currentData()
        if not isinstance(template_id, str):
            self.error_label.setText("请选择步骤模板")
            return
        try:
            step = build_template_step(
                template_id,
                self._parameters(),
                project=self.project,
                current_workflow_id=self.current_workflow_id,
            )
            errors = _project_with_step(
                self.project,
                self.current_workflow_id,
                step,
            ).validate_references()
            if errors:
                raise ValueError("；".join(errors))
        except ValueError as error:
            self.error_label.setText(str(error))
            return
        self._step = step
        super().accept()

    def step(self) -> AutomationStep:
        if self._step is None:
            raise RuntimeError("template step dialog has not been accepted")
        return self._step

    def _template_changed(self) -> None:
        template_id = self.template_combo.currentData()
        if not isinstance(template_id, str):
            return
        template = STEP_TEMPLATES[template_id]
        self.name_edit.setText(template.name)
        parameters = set(template.parameters)
        controls = {
            "keywords": self.keywords_edit,
            "seconds": self.seconds_spin,
            "timeout_seconds": self.timeout_spin,
            "key": self.key_edit,
            "window_process_name": self.window_process_name_edit,
            "target_step_id": self.target_step_combo,
            "target_workflow_id": self.target_workflow_combo,
            "success_workflow_id": self.success_workflow_combo,
            "timeout_workflow_id": self.timeout_workflow_combo,
        }
        for name, control in controls.items():
            self.form.setRowVisible(control, name in parameters)
        self.error_label.clear()

    def _populate_targets(self) -> None:
        labels = ProjectDisplayIndex(self.project)
        for group in self.project.groups:
            for workflow in group.workflows:
                label = labels.workflow_path(workflow.id)
                for combo in (
                    self.target_workflow_combo,
                    self.success_workflow_combo,
                    self.timeout_workflow_combo,
                ):
                    combo.addItem(label, workflow.id)
                if workflow.id == self.current_workflow_id:
                    for step in workflow.steps:
                        self.target_step_combo.addItem(labels.step_label(step.id), step.id)

    def _parameters(self) -> dict[str, object]:
        return {
            "name": self.name_edit.text(),
            "keywords": self.keywords_edit.text(),
            "seconds": self.seconds_spin.value(),
            "timeout_seconds": self.timeout_spin.value(),
            "key": self.key_edit.text(),
            "window_process_name": self.window_process_name_edit.text(),
            "target_step_id": self.target_step_combo.currentData(),
            "target_workflow_id": self.target_workflow_combo.currentData(),
            "success_workflow_id": self.success_workflow_combo.currentData(),
            "timeout_workflow_id": self.timeout_workflow_combo.currentData(),
        }


def _project_with_step(
    project: Project,
    workflow_id: UUID,
    step: AutomationStep,
) -> Project:
    groups = []
    for group in project.groups:
        workflows = [
            workflow.model_copy(update={"steps": [*workflow.steps, step]})
            if workflow.id == workflow_id
            else workflow
            for workflow in group.workflows
        ]
        groups.append(group.model_copy(update={"workflows": workflows}))
    return project.model_copy(update={"groups": groups})

from uuid import UUID

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
)

from flow_runner.display_labels import ProjectDisplayIndex
from flow_runner.domain.project import ParallelBlock, Project


class ParallelBlockDialog(QDialog):
    def __init__(self, project: Project, block: ParallelBlock | None = None) -> None:
        super().__init__()
        self._source_block = block
        self._block: ParallelBlock | None = None
        self.name_edit = QLineEdit()
        if block is not None:
            self.name_edit.setText(block.name)
        self.workflow_list = QListWidget()
        labels = ProjectDisplayIndex(project)
        for group in project.groups:
            for workflow in group.workflows:
                item = QListWidgetItem(labels.workflow_path(workflow.id))
                item.setData(Qt.ItemDataRole.UserRole, workflow.id)
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(
                    Qt.CheckState.Checked
                    if block is not None and workflow.id in block.workflow_ids
                    else Qt.CheckState.Unchecked
                )
                self.workflow_list.addItem(item)
        self.error_label = QLabel("")
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout = QFormLayout(self)
        layout.addRow("名称", self.name_edit)
        layout.addRow("并行流程", self.workflow_list)
        layout.addRow("", self.error_label)
        layout.addRow(self.buttons)

    def accept(self) -> None:
        workflow_ids: list[UUID] = []
        for index in range(self.workflow_list.count()):
            item = self.workflow_list.item(index)
            if item.checkState() is Qt.CheckState.Checked:
                workflow_id = item.data(Qt.ItemDataRole.UserRole)
                if isinstance(workflow_id, UUID):
                    workflow_ids.append(workflow_id)
        try:
            values: dict[str, object] = {
                "name": self.name_edit.text().strip(),
                "workflow_ids": workflow_ids,
            }
            if self._source_block is not None:
                values["id"] = self._source_block.id
            self._block = ParallelBlock.model_validate(values)
        except ValueError as error:
            self.error_label.setText(str(error))
            return
        super().accept()

    def block(self) -> ParallelBlock:
        if self._block is None:
            raise RuntimeError("parallel block dialog has not been accepted")
        return self._block

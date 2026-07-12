from uuid import UUID

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from flow_runner.domain.project import Workflow


class StepListPanel(QWidget):
    stepSelected = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("stepListPanel")
        self.list = QListWidget()
        layout = QVBoxLayout(self)
        layout.addWidget(self.list)
        self._items: dict[UUID, QListWidgetItem] = {}
        self.list.currentItemChanged.connect(self._on_current_item)

    def set_workflow(self, workflow: Workflow) -> None:
        self.list.clear()
        self._items.clear()
        for step in workflow.steps:
            item = QListWidgetItem(step.name)
            item.setData(Qt.ItemDataRole.UserRole, step.id)
            self.list.addItem(item)
            self._items[step.id] = item

    def select_step(self, step_id: UUID) -> None:
        self.list.setCurrentItem(self._items[step_id])

    def _on_current_item(self, current: QListWidgetItem | None) -> None:
        if current is None:
            return
        step_id = current.data(Qt.ItemDataRole.UserRole)
        if isinstance(step_id, UUID):
            self.stepSelected.emit(step_id)

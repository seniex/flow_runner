from uuid import UUID

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from flow_runner.domain.project import Project


class FlowTreePanel(QWidget):
    workflowSelected = Signal(object)

    def __init__(self, project: Project) -> None:
        super().__init__()
        self.setObjectName("flowTreePanel")
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tree)
        self._items: dict[UUID, QTreeWidgetItem] = {}
        self.tree.currentItemChanged.connect(self._on_current_item)
        self.set_project(project)

    def set_project(self, project: Project) -> None:
        self.tree.clear()
        self._items.clear()
        for group in project.groups:
            group_item = QTreeWidgetItem([group.name])
            self.tree.addTopLevelItem(group_item)
            for workflow in group.workflows:
                item = QTreeWidgetItem([workflow.name])
                item.setData(0, Qt.ItemDataRole.UserRole, workflow.id)
                group_item.addChild(item)
                self._items[workflow.id] = item
            group_item.setExpanded(True)

    def select_workflow(self, workflow_id: UUID) -> None:
        self.tree.setCurrentItem(self._items[workflow_id])

    def _on_current_item(self, current: QTreeWidgetItem | None) -> None:
        if current is None:
            return
        workflow_id = current.data(0, Qt.ItemDataRole.UserRole)
        if isinstance(workflow_id, UUID):
            self.workflowSelected.emit(workflow_id)

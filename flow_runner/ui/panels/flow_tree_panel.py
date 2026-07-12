from uuid import UUID

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from flow_runner.domain.project import Project


class FlowTreePanel(QWidget):
    groupSelected = Signal(object)
    workflowSelected = Signal(object)

    def __init__(self, project: Project) -> None:
        super().__init__()
        self.setObjectName("flowTreePanel")
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.tree)
        self._items: dict[UUID, QTreeWidgetItem] = {}
        self._group_items: dict[UUID, QTreeWidgetItem] = {}
        self.tree.currentItemChanged.connect(self._on_current_item)
        self.set_project(project)

    def set_project(self, project: Project) -> None:
        self.tree.clear()
        self._items.clear()
        self._group_items.clear()
        for group in project.groups:
            group_item = QTreeWidgetItem([group.name])
            group_item.setData(0, Qt.ItemDataRole.UserRole, group.id)
            group_item.setData(0, int(Qt.ItemDataRole.UserRole) + 1, "group")
            self.tree.addTopLevelItem(group_item)
            self._group_items[group.id] = group_item
            for workflow in group.workflows:
                item = QTreeWidgetItem([workflow.name])
                item.setData(0, Qt.ItemDataRole.UserRole, workflow.id)
                item.setData(0, int(Qt.ItemDataRole.UserRole) + 1, "workflow")
                group_item.addChild(item)
                self._items[workflow.id] = item
            group_item.setExpanded(True)

    def select_workflow(self, workflow_id: UUID) -> None:
        self.tree.setCurrentItem(self._items[workflow_id])

    def select_group(self, group_id: UUID) -> None:
        self.tree.setCurrentItem(self._group_items[group_id])

    def _on_current_item(self, current: QTreeWidgetItem | None) -> None:
        if current is None:
            return
        workflow_id = current.data(0, Qt.ItemDataRole.UserRole)
        kind = current.data(0, int(Qt.ItemDataRole.UserRole) + 1)
        if kind == "workflow" and isinstance(workflow_id, UUID):
            self.workflowSelected.emit(workflow_id)
        elif kind == "group" and isinstance(workflow_id, UUID):
            self.groupSelected.emit(workflow_id)

from uuid import UUID

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMainWindow, QSplitter

from flow_runner.domain.project import Project, Workflow
from flow_runner.ui.panels.flow_tree_panel import FlowTreePanel
from flow_runner.ui.panels.property_panel import PropertyPanel
from flow_runner.ui.panels.step_list_panel import StepListPanel
from flow_runner.ui.view_models.project_view_model import ProjectViewModel


class MainWindow(QMainWindow):
    def __init__(self, project: Project) -> None:
        super().__init__()
        self.view_model = ProjectViewModel(project)
        self.flow_tree = FlowTreePanel(project)
        self.step_list = StepListPanel()
        self.property_panel = PropertyPanel()
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.flow_tree)
        splitter.addWidget(self.step_list)
        splitter.addWidget(self.property_panel)
        self.setCentralWidget(splitter)
        self.flow_tree.workflowSelected.connect(self._select_workflow)
        self.step_list.stepSelected.connect(self._select_step)
        self.view_model.projectChanged.connect(self.flow_tree.set_project)
        self._workflow_id: UUID | None = None

    def _select_workflow(self, workflow_id: UUID) -> None:
        workflow = self._workflow(workflow_id)
        self._workflow_id = workflow.id
        self.step_list.set_workflow(workflow)

    def _select_step(self, step_id: UUID) -> None:
        if self._workflow_id is None:
            return
        workflow = self._workflow(self._workflow_id)
        step = next(step for step in workflow.steps if step.id == step_id)
        self.property_panel.set_step(step)

    def _workflow(self, workflow_id: UUID) -> Workflow:
        for group in self.view_model.project.groups:
            for workflow in group.workflows:
                if workflow.id == workflow_id:
                    return workflow
        raise KeyError(workflow_id)

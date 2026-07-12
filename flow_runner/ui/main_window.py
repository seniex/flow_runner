from uuid import UUID

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import QMainWindow, QSplitter, QToolBar

from flow_runner.domain.enums import RunnerState
from flow_runner.domain.project import Project, Workflow
from flow_runner.ui.panels.flow_tree_panel import FlowTreePanel
from flow_runner.ui.panels.property_panel import PropertyPanel
from flow_runner.ui.panels.step_list_panel import StepListPanel
from flow_runner.ui.runner_bridge import RunnerBridge
from flow_runner.ui.view_models.project_view_model import ProjectViewModel
from flow_runner.ui.view_models.run_view_model import RunViewModel


class MainWindow(QMainWindow):
    startRequested = Signal()
    pauseRequested = Signal()
    stopRequested = Signal()

    def __init__(self, project: Project, *, runner_bridge: RunnerBridge | None = None) -> None:
        super().__init__()
        self.view_model = ProjectViewModel(project)
        self.run_view_model = RunViewModel()
        self.runner_bridge = runner_bridge
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
        self.runtime_toolbar = QToolBar("运行", self)
        self.runtime_toolbar.setObjectName("runtimeToolbar")
        self.addToolBar(self.runtime_toolbar)
        self.start_action = QAction("启动", self)
        self.start_action.setObjectName("startWorkflowAction")
        self.pause_action = QAction("暂停", self)
        self.pause_action.setObjectName("pauseWorkflowAction")
        self.stop_action = QAction("停止", self)
        self.stop_action.setObjectName("stopWorkflowAction")
        self.runtime_toolbar.addActions([self.start_action, self.pause_action, self.stop_action])
        self.start_action.triggered.connect(self._start_selected_workflow)
        self.pause_action.triggered.connect(self._toggle_pause)
        self.stop_action.triggered.connect(self._stop_runtime)
        self.startRequested.connect(self._start_selected_workflow)
        self.pauseRequested.connect(self._toggle_pause)
        self.stopRequested.connect(self._stop_runtime)
        self.run_view_model.stateChanged.connect(self._update_runtime_actions)
        if self.runner_bridge is not None:
            self.runner_bridge.eventReceived.connect(self.run_view_model.consume)
            self.runner_bridge.failed.connect(self.statusBar().showMessage)
        self._update_runtime_actions(self.run_view_model.state)

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

    def _start_selected_workflow(self) -> None:
        if self.runner_bridge is None:
            self.statusBar().showMessage("运行服务尚未配置")
            return
        if self._workflow_id is None:
            self.statusBar().showMessage("请先选择要启动的流程")
            return
        self.runner_bridge.start(self.view_model.project, self._workflow_id)

    def _toggle_pause(self) -> None:
        if self.runner_bridge is None:
            return
        if self.run_view_model.state is RunnerState.PAUSED:
            self.runner_bridge.resume()
        else:
            self.runner_bridge.pause()

    def _stop_runtime(self) -> None:
        if self.runner_bridge is not None:
            self.runner_bridge.stop()

    def _update_runtime_actions(self, state: RunnerState) -> None:
        active = state in {RunnerState.RUNNING, RunnerState.PAUSED}
        self.start_action.setEnabled(not active)
        self.pause_action.setEnabled(active)
        self.stop_action.setEnabled(active)
        self.pause_action.setText("继续" if state is RunnerState.PAUSED else "暂停")

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.runner_bridge is not None:
            self.runner_bridge.shutdown()
        super().closeEvent(event)

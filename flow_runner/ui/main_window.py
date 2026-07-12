from collections.abc import Callable
from typing import Literal
from uuid import UUID

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent
from PySide6.QtWidgets import QInputDialog, QMainWindow, QMessageBox, QSplitter, QToolBar

from flow_runner.capabilities.registry import CapabilityRegistry
from flow_runner.domain.enums import RunnerState
from flow_runner.domain.project import AutomationStep, FlowGroup, ParallelBlock, Project, Workflow
from flow_runner.ui.dialogs.diagnostics_dialog import DiagnosticsDialog
from flow_runner.ui.dialogs.guided_add_dialog import GuidedAddDialog
from flow_runner.ui.dialogs.parallel_block_dialog import ParallelBlockDialog
from flow_runner.ui.dialogs.settings_dialog import SettingsDialog
from flow_runner.ui.hotkeys import HotkeyConfig
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
    recordRequested = Signal()

    def __init__(
        self,
        project: Project,
        *,
        runner_bridge: RunnerBridge | None = None,
        save_project: Callable[[Project], None] | None = None,
        confirm_close: Callable[[], Literal["save", "discard", "cancel"]] | None = None,
        registry: CapabilityRegistry | None = None,
        create_step: Callable[[], AutomationStep | None] | None = None,
        request_name: Callable[[str, str], str | None] | None = None,
        confirm_delete: Callable[[str], bool] | None = None,
        edit_settings: Callable[[dict[str, object]], dict[str, object] | None] | None = None,
        create_parallel_block: Callable[[], ParallelBlock | None] | None = None,
    ) -> None:
        super().__init__()
        self.view_model = ProjectViewModel(project)
        self.run_view_model = RunViewModel()
        self.runner_bridge = runner_bridge
        self.save_project = save_project
        self._confirm_close_injected = confirm_close is not None
        self.confirm_close = confirm_close or self._confirm_dirty_close
        self.registry = registry
        self.create_step = create_step or self._prompt_new_step
        self.request_name = request_name or self._request_name
        self.confirm_delete = confirm_delete or self._confirm_delete
        self.edit_settings = edit_settings or self._prompt_settings
        self.create_parallel_block = create_parallel_block or self._prompt_parallel_block
        self.flow_tree = FlowTreePanel(project)
        self.step_list = StepListPanel()
        self.property_panel = PropertyPanel(registry, project)
        self.diagnostics_dialog = DiagnosticsDialog(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.flow_tree)
        splitter.addWidget(self.step_list)
        splitter.addWidget(self.property_panel)
        self.setCentralWidget(splitter)
        self.flow_tree.workflowSelected.connect(self._select_workflow)
        self.flow_tree.groupSelected.connect(self._select_group)
        self.flow_tree.parallelBlockSelected.connect(self._select_parallel_block)
        self.step_list.stepSelected.connect(self._select_step)
        self.view_model.projectChanged.connect(self._project_changed)
        self.property_panel.stepChanged.connect(self._apply_step_edit)
        self.property_panel.validationFailed.connect(self.statusBar().showMessage)
        self._workflow_id: UUID | None = None
        self._group_id: UUID | None = None
        self._parallel_block_id: UUID | None = None
        self.runtime_toolbar = QToolBar("运行", self)
        self.runtime_toolbar.setObjectName("runtimeToolbar")
        self.addToolBar(self.runtime_toolbar)
        self.project_toolbar = QToolBar("项目", self)
        self.project_toolbar.setObjectName("projectToolbar")
        self.addToolBar(self.project_toolbar)
        self.save_action = QAction("保存", self)
        self.save_action.setObjectName("saveProjectAction")
        self.undo_action = QAction("撤销", self)
        self.undo_action.setObjectName("undoProjectAction")
        self.add_step_action = QAction("新增步骤", self)
        self.add_step_action.setObjectName("addStepAction")
        self.remove_step_action = QAction("删除步骤", self)
        self.remove_step_action.setObjectName("removeStepAction")
        self.move_step_up_action = QAction("上移步骤", self)
        self.move_step_up_action.setObjectName("moveStepUpAction")
        self.move_step_down_action = QAction("下移步骤", self)
        self.move_step_down_action.setObjectName("moveStepDownAction")
        self.add_group_action = QAction("新增组", self)
        self.add_group_action.setObjectName("addGroupAction")
        self.add_workflow_action = QAction("新增流程", self)
        self.add_workflow_action.setObjectName("addWorkflowAction")
        self.rename_flow_action = QAction("重命名", self)
        self.rename_flow_action.setObjectName("renameFlowAction")
        self.delete_flow_action = QAction("删除组/流程", self)
        self.delete_flow_action.setObjectName("deleteFlowAction")
        self.settings_action = QAction("设置", self)
        self.settings_action.setObjectName("projectSettingsAction")
        self.add_parallel_action = QAction("新增并行块", self)
        self.add_parallel_action.setObjectName("addParallelBlockAction")
        self.delete_parallel_action = QAction("删除并行块", self)
        self.delete_parallel_action.setObjectName("deleteParallelBlockAction")
        self.project_toolbar.addActions(
            [
                self.save_action,
                self.undo_action,
                self.add_group_action,
                self.add_workflow_action,
                self.rename_flow_action,
                self.delete_flow_action,
                self.settings_action,
                self.add_parallel_action,
                self.delete_parallel_action,
                self.add_step_action,
                self.remove_step_action,
                self.move_step_up_action,
                self.move_step_down_action,
            ]
        )
        self.save_action.setEnabled(False)
        self.start_action = QAction("启动", self)
        self.start_action.setObjectName("startWorkflowAction")
        self.pause_action = QAction("暂停", self)
        self.pause_action.setObjectName("pauseWorkflowAction")
        self.stop_action = QAction("停止", self)
        self.stop_action.setObjectName("stopWorkflowAction")
        self.record_action = QAction("录制", self)
        self.record_action.setObjectName("recordAction")
        self.diagnostics_action = QAction("诊断", self)
        self.diagnostics_action.setObjectName("diagnosticsAction")
        self.runtime_toolbar.addActions(
            [
                self.start_action,
                self.pause_action,
                self.stop_action,
                self.record_action,
                self.diagnostics_action,
            ]
        )
        self.start_action.triggered.connect(self._start_selected_workflow)
        self.pause_action.triggered.connect(self._toggle_pause)
        self.stop_action.triggered.connect(self._stop_runtime)
        self.record_action.triggered.connect(self.recordRequested.emit)
        self.diagnostics_action.triggered.connect(self.diagnostics_dialog.show)
        self.save_action.triggered.connect(self._save_project)
        self.undo_action.triggered.connect(self.view_model.undo)
        self.add_step_action.triggered.connect(self._add_step)
        self.remove_step_action.triggered.connect(self._remove_selected_step)
        self.move_step_up_action.triggered.connect(lambda: self._move_selected_step(-1))
        self.move_step_down_action.triggered.connect(lambda: self._move_selected_step(1))
        self.add_group_action.triggered.connect(self._add_group)
        self.add_workflow_action.triggered.connect(self._add_workflow)
        self.rename_flow_action.triggered.connect(self._rename_selected_flow)
        self.delete_flow_action.triggered.connect(self._delete_selected_flow)
        self.settings_action.triggered.connect(self._edit_project_settings)
        self.add_parallel_action.triggered.connect(self._add_parallel_block)
        self.delete_parallel_action.triggered.connect(self._delete_parallel_block)
        self.startRequested.connect(self._start_selected_workflow)
        self.pauseRequested.connect(self._toggle_pause)
        self.stopRequested.connect(self._stop_runtime)
        self.run_view_model.stateChanged.connect(self._update_runtime_actions)
        if self.runner_bridge is not None:
            self.runner_bridge.eventReceived.connect(self.run_view_model.consume)
            self.runner_bridge.eventReceived.connect(self.diagnostics_dialog.update_event)
            self.runner_bridge.failed.connect(self.statusBar().showMessage)
        self._update_runtime_actions(self.run_view_model.state)

    def _select_workflow(self, workflow_id: UUID) -> None:
        workflow = self._workflow(workflow_id)
        self._group_id = self._group_for_workflow(workflow_id).id
        self._workflow_id = workflow.id
        self._parallel_block_id = None
        self.step_list.set_workflow(workflow)

    def _select_group(self, group_id: UUID) -> None:
        self._group_id = group_id
        self._workflow_id = None
        self._parallel_block_id = None
        self.step_list.set_workflow(Workflow(name="空"))
        self.property_panel.clear_step()

    def _select_parallel_block(self, block_id: UUID) -> None:
        self._parallel_block_id = block_id
        self._group_id = None
        self._workflow_id = None
        self.step_list.set_workflow(Workflow(name="空"))
        self.property_panel.clear_step()

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

    def _group_for_workflow(self, workflow_id: UUID) -> FlowGroup:
        for group in self.view_model.project.groups:
            if any(workflow.id == workflow_id for workflow in group.workflows):
                return group
        raise KeyError(workflow_id)

    def _apply_step_edit(self, step: object) -> None:
        if self._workflow_id is None or not isinstance(step, AutomationStep):
            return
        self.view_model.update_step(self._workflow_id, step)

    def _project_changed(self, project: Project) -> None:
        self.save_action.setEnabled(self.view_model.dirty)
        self.property_panel.set_project(project)
        self.flow_tree.set_project(project)
        if self._parallel_block_id is not None:
            try:
                self.flow_tree.select_parallel_block(self._parallel_block_id)
            except KeyError:
                self._parallel_block_id = None
            return
        if self._workflow_id is None:
            if self._group_id is not None:
                try:
                    self.flow_tree.select_group(self._group_id)
                except KeyError:
                    self._group_id = None
            return
        try:
            workflow = self._workflow(self._workflow_id)
        except KeyError:
            self._workflow_id = None
            self.step_list.set_workflow(Workflow(name="空"))
            return
        self.flow_tree.select_workflow(workflow.id)
        if self.property_panel.step_id is not None:
            try:
                self.step_list.select_step(self.property_panel.step_id)
            except KeyError:
                pass

    def _save_project(self) -> bool:
        if self.save_project is None:
            self.statusBar().showMessage("未配置项目保存服务")
            return False
        try:
            self.save_project(self.view_model.project)
        except Exception as error:
            self.statusBar().showMessage(f"项目保存失败：{error}")
            return False
        self.view_model.mark_saved()
        self.save_action.setEnabled(False)
        self.statusBar().showMessage("项目已保存")
        return True

    def _add_step(self) -> None:
        if self._workflow_id is None:
            self.statusBar().showMessage("请先选择要添加步骤的流程")
            return
        step = self.create_step()
        if step is None:
            return
        self.view_model.add_step(self._workflow_id, step)
        self.step_list.select_step(step.id)

    def _remove_selected_step(self) -> None:
        if self._workflow_id is None or self.property_panel.step_id is None:
            self.statusBar().showMessage("请先选择要删除的步骤")
            return
        step_id = self.property_panel.step_id
        self.view_model.remove_step(self._workflow_id, step_id)
        self.property_panel.clear_step()

    def _move_selected_step(self, direction: int) -> None:
        if self._workflow_id is None or self.property_panel.step_id is None:
            self.statusBar().showMessage("请先选择要移动的步骤")
            return
        step_id = self.property_panel.step_id
        self.view_model.move_step(self._workflow_id, step_id, direction)
        self.step_list.select_step(step_id)

    def _prompt_new_step(self) -> AutomationStep | None:
        if self.registry is None:
            self.statusBar().showMessage("未配置能力注册表")
            return None
        dialog = GuidedAddDialog(self.registry)
        if dialog.exec() != GuidedAddDialog.DialogCode.Accepted:
            return None
        return dialog.step()

    def _add_group(self) -> None:
        name = self.request_name("group", "")
        if not name:
            return
        group = FlowGroup(name=name)
        self.view_model.add_group(group)
        self.flow_tree.select_group(group.id)

    def _add_workflow(self) -> None:
        if self._group_id is None:
            self.statusBar().showMessage("请先选择流程组")
            return
        name = self.request_name("workflow", "")
        if not name:
            return
        workflow = Workflow(name=name)
        self.view_model.add_workflow(self._group_id, workflow)
        self.flow_tree.select_workflow(workflow.id)

    def _rename_selected_flow(self) -> None:
        if self._workflow_id is not None:
            workflow = self._workflow(self._workflow_id)
            name = self.request_name("workflow", workflow.name)
            if name:
                self.view_model.rename_workflow(workflow.id, name)
            return
        if self._group_id is not None:
            group = next(
                group for group in self.view_model.project.groups if group.id == self._group_id
            )
            name = self.request_name("group", group.name)
            if name:
                self.view_model.rename_group(group.id, name)
            return
        self.statusBar().showMessage("请先选择流程组或流程")

    def _delete_selected_flow(self) -> None:
        if self._workflow_id is not None:
            workflow = self._workflow(self._workflow_id)
            if self.confirm_delete(f"流程“{workflow.name}”"):
                self.view_model.remove_workflow(workflow.id)
                self._workflow_id = None
            return
        if self._group_id is not None:
            group = next(
                group for group in self.view_model.project.groups if group.id == self._group_id
            )
            if self.confirm_delete(f"流程组“{group.name}”"):
                self.view_model.remove_group(group.id)
                self._group_id = None
            return
        self.statusBar().showMessage("请先选择流程组或流程")

    def _request_name(self, kind: str, current: str) -> str | None:
        title = "流程组名称" if kind == "group" else "流程名称"
        value, accepted = QInputDialog.getText(self, title, title, text=current)
        return value.strip() if accepted and value.strip() else None

    def _confirm_delete(self, label: str) -> bool:
        return (
            QMessageBox.question(self, "确认删除", f"确定删除{label}？")
            is QMessageBox.StandardButton.Yes
        )

    def _edit_project_settings(self) -> None:
        settings = self.edit_settings(dict(self.view_model.project.settings))
        if settings is None:
            return
        self.view_model.update_settings(settings)
        self.statusBar().showMessage("设置已更新；OCR 引擎和全局热键将在下次启动时生效")

    def _prompt_settings(self, settings: dict[str, object]) -> dict[str, object] | None:
        hotkeys = HotkeyConfig.model_validate(settings.get("hotkeys", {}))
        dialog = SettingsDialog(hotkeys, settings)
        if dialog.exec() != SettingsDialog.DialogCode.Accepted:
            return None
        return dialog.project_settings()

    def _add_parallel_block(self) -> None:
        block = self.create_parallel_block()
        if block is None:
            return
        self.view_model.add_parallel_block(block)
        self.flow_tree.select_parallel_block(block.id)

    def _delete_parallel_block(self) -> None:
        if self._parallel_block_id is None:
            self.statusBar().showMessage("请先选择并行监控块")
            return
        block = next(
            block
            for block in self.view_model.project.parallel_blocks
            if block.id == self._parallel_block_id
        )
        if self.confirm_delete(f"并行监控块“{block.name}”"):
            self.view_model.remove_parallel_block(block.id)
            self._parallel_block_id = None

    def _prompt_parallel_block(self) -> ParallelBlock | None:
        dialog = ParallelBlockDialog(self.view_model.project)
        if dialog.exec() != ParallelBlockDialog.DialogCode.Accepted:
            return None
        return dialog.block()

    def _start_selected_workflow(self) -> None:
        if self.runner_bridge is None:
            self.statusBar().showMessage("运行服务尚未配置")
            return
        if self._parallel_block_id is not None:
            self.runner_bridge.start_parallel(
                self.view_model.project,
                self._parallel_block_id,
            )
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
        if self.view_model.dirty and (self.isVisible() or self._confirm_close_injected):
            decision = self.confirm_close()
            if decision == "cancel" or (decision == "save" and not self._save_project()):
                event.ignore()
                return
        if self.runner_bridge is not None:
            self.runner_bridge.shutdown()
        super().closeEvent(event)

    def set_recording_state(self, recording: bool) -> None:
        self.record_action.setText("停止录制" if recording else "录制")
        self.record_action.setProperty("status", "recording" if recording else "idle")

    def _confirm_dirty_close(self) -> Literal["save", "discard", "cancel"]:
        button = QMessageBox.warning(
            self,
            "未保存的更改",
            "项目包含未保存的更改。",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if button is QMessageBox.StandardButton.Save:
            return "save"
        if button is QMessageBox.StandardButton.Discard:
            return "discard"
        return "cancel"

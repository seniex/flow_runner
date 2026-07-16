from collections.abc import Callable
from datetime import datetime
from inspect import signature
from pathlib import Path
from uuid import UUID

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from flow_runner.capabilities.registry import CapabilityRegistry
from flow_runner.display_labels import ProjectDisplayIndex
from flow_runner.domain.enums import RunnerState
from flow_runner.domain.project import AutomationStep, FlowGroup, ParallelBlock, Project, Workflow
from flow_runner.infrastructure.logging.formatters import RuntimeEventFormatter
from flow_runner.ui.capture_preferences import CapturePreferences
from flow_runner.ui.dialogs.close_confirmation_dialog import (
    CloseConfirmationDialog,
    CloseDecision,
)
from flow_runner.ui.dialogs.diagnostics_dialog import DiagnosticsDialog
from flow_runner.ui.dialogs.guided_add_dialog import GuidedAddDialog
from flow_runner.ui.dialogs.parallel_block_dialog import ParallelBlockDialog
from flow_runner.ui.dialogs.settings_dialog import SettingsDialog
from flow_runner.ui.dialogs.template_step_dialog import TemplateStepDialog
from flow_runner.ui.flow_tree_preferences import FlowTreePreferences
from flow_runner.ui.hotkeys import HotkeyConfig
from flow_runner.ui.icons import ACTION_ICON_NAMES, icon
from flow_runner.ui.panels.flow_tree_panel import FlowTreePanel
from flow_runner.ui.panels.property_panel import PropertyPanel
from flow_runner.ui.panels.step_list_panel import StepListPanel
from flow_runner.ui.region_capture import PointCaptureService, RegionCaptureService
from flow_runner.ui.runner_bridge import RunnerBridge
from flow_runner.ui.runtime_log import RuntimeLogController
from flow_runner.ui.view_models.project_view_model import ProjectViewModel
from flow_runner.ui.view_models.run_view_model import RunViewModel
from flow_runner.ui.widgets import ColumnContainer, FocusWheelComboBox, ResponsiveControlArea
from flow_runner.ui.window_preferences import WindowPreferences


class MainWindow(QMainWindow):
    startRequested = Signal()
    pauseRequested = Signal()
    stopRequested = Signal()
    recordRequested = Signal()
    recordPauseRequested = Signal()
    hotkeyConfigChanged = Signal(object)
    runtimePauseChanged = Signal(bool)
    runtimeStopAccepted = Signal()

    def __init__(
        self,
        project: Project,
        *,
        runner_bridge: RunnerBridge | None = None,
        save_project: Callable[[Project], None] | None = None,
        project_path: Path | None = None,
        confirm_close: Callable[..., CloseDecision | str] | None = None,
        registry: CapabilityRegistry | None = None,
        create_step: Callable[[], AutomationStep | None] | None = None,
        create_template_step: Callable[[], AutomationStep | None] | None = None,
        request_name: Callable[[str, str], str | None] | None = None,
        confirm_delete: Callable[[str], bool] | None = None,
        edit_settings: Callable[[dict[str, object]], dict[str, object] | None] | None = None,
        create_parallel_block: Callable[[], ParallelBlock | None] | None = None,
        edit_parallel_block: Callable[[ParallelBlock], ParallelBlock | None] | None = None,
        select_group_target: Callable[[Project, UUID], UUID | None] | None = None,
        region_capture: RegionCaptureService | None = None,
        point_capture: PointCaptureService | None = None,
        capture_preferences: CapturePreferences | None = None,
        runtime_formatter: RuntimeEventFormatter | None = None,
        window_preferences: WindowPreferences | None = None,
        flow_tree_preferences: FlowTreePreferences | None = None,
    ) -> None:
        super().__init__()
        self.view_model = ProjectViewModel(project)
        self.run_view_model = RunViewModel()
        self.runner_bridge = runner_bridge
        self.save_project = save_project
        self.project_path = project_path
        self._confirm_close_injected = confirm_close is not None
        self.confirm_close: Callable[..., CloseDecision | str] = (
            confirm_close or self._confirm_close
        )
        self._confirm_close_accepts_state = _accepts_close_state(self.confirm_close)
        self.registry = registry
        self.region_capture = region_capture
        self.point_capture = point_capture
        self.capture_preferences = capture_preferences or CapturePreferences()
        self.window_preferences = window_preferences or WindowPreferences()
        self.flow_tree_preferences = flow_tree_preferences or FlowTreePreferences()
        self._saved_column_widths = _column_widths_from_settings(project.settings)
        self._pending_column_widths: tuple[int, int, int] | None = None
        self._layout_dirty = False
        self.create_step = create_step or self._prompt_new_step
        self.create_template_step = create_template_step or self._prompt_template_step
        self.request_name = request_name or self._request_name
        self.confirm_delete = confirm_delete or self._confirm_delete
        self.edit_settings = edit_settings or self._prompt_settings
        self.create_parallel_block = create_parallel_block or self._prompt_parallel_block
        self.edit_parallel_block = edit_parallel_block or self._prompt_edit_parallel_block
        self.select_group_target = select_group_target or self._prompt_workflow_group
        self.flow_tree = FlowTreePanel(project)
        self.step_list = StepListPanel()
        self.property_panel = PropertyPanel(
            registry,
            project,
            apply_step=self._apply_step_edit,
            region_capture=region_capture,
            point_capture=point_capture,
            capture_preferences=self.capture_preferences,
        )
        self.diagnostics_dialog = DiagnosticsDialog(self)
        self.runtime_log = QPlainTextEdit()
        self.runtime_log.setObjectName("runtimeLog")
        self.runtime_log.setReadOnly(True)
        self.runtime_log.setPlaceholderText("运行日志将在这里显示")
        self.runtime_formatter = runtime_formatter or RuntimeEventFormatter(
            project,
            debug=bool(project.settings.get("debug_logging", False)),
        )
        self.runtime_log_controller = RuntimeLogController(
            self.runtime_log,
            self.runtime_formatter,
        )
        self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.workspace_splitter.setObjectName("workspaceSplitter")
        self.workspace_splitter.setStretchFactor(0, 1)
        self.workspace_splitter.setStretchFactor(1, 2)
        self.workspace_splitter.setStretchFactor(2, 3)
        self.content_splitter = QSplitter(Qt.Orientation.Vertical)
        self.content_splitter.setObjectName("contentSplitter")
        self.content_splitter.addWidget(self.workspace_splitter)
        self.content_splitter.addWidget(self.runtime_log)
        self.content_splitter.setStretchFactor(0, 5)
        self.content_splitter.setStretchFactor(1, 1)
        workspace = QWidget()
        workspace.setObjectName("simpleWorkspace")
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(8, 8, 8, 8)
        workspace_layout.addWidget(self.content_splitter)
        self.setCentralWidget(workspace)
        self.flow_tree.workflowSelected.connect(self._select_workflow)
        self.flow_tree.groupSelected.connect(self._select_group)
        self.flow_tree.parallelBlockSelected.connect(self._select_parallel_block)
        self.flow_tree.groupExpansionChanged.connect(self._flow_group_expansion_changed)
        self._restore_flow_group_expansion()
        self.step_list.stepSelected.connect(self._select_step)
        self.view_model.projectChanged.connect(self._project_changed)
        self.view_model.historyChanged.connect(self._history_changed)
        self.property_panel.validationFailed.connect(self.statusBar().showMessage)
        self.property_panel.pendingChanged.connect(self._pending_changed)
        self._workflow_id: UUID | None = None
        self._group_id: UUID | None = None
        self._parallel_block_id: UUID | None = None
        self.startup_group_combo = FocusWheelComboBox()
        self.startup_group_combo.setObjectName("startupGroupCombo")
        self.startup_workflow_combo = FocusWheelComboBox()
        self.startup_workflow_combo.setObjectName("startupWorkflowCombo")
        self.save_action = QAction("保存", self)
        self.save_action.setObjectName("saveProjectAction")
        self.save_action.setToolTip("保存项目（Ctrl+S）")
        self.save_shortcut = QShortcut(QKeySequence(QKeySequence.StandardKey.Save), self)
        self.save_shortcut.setObjectName("saveProjectShortcut")
        self.save_shortcut.activated.connect(self._save_project)
        self.undo_action = QAction("撤销", self)
        self.undo_action.setObjectName("undoProjectAction")
        self.add_step_action = QAction("新增步骤", self)
        self.add_step_action.setObjectName("addStepAction")
        self.add_template_step_action = QAction("从模板新增步骤", self)
        self.add_template_step_action.setObjectName("addTemplateStepAction")
        self.remove_step_action = QAction("删除步骤", self)
        self.remove_step_action.setObjectName("removeStepAction")
        self.move_step_up_action = QAction("上移步骤", self)
        self.move_step_up_action.setObjectName("moveStepUpAction")
        self.move_step_down_action = QAction("下移步骤", self)
        self.move_step_down_action.setObjectName("moveStepDownAction")
        self.add_group_action = QAction("新增组", self)
        self.add_group_action.setObjectName("addGroupAction")
        self.copy_group_action = QAction("复制流程组", self)
        self.copy_group_action.setObjectName("copyGroupAction")
        self.add_workflow_action = QAction("新增流程", self)
        self.add_workflow_action.setObjectName("addWorkflowAction")
        self.copy_workflow_action = QAction("复制流程", self)
        self.copy_workflow_action.setObjectName("copyWorkflowAction")
        self.rename_flow_action = QAction("重命名", self)
        self.rename_flow_action.setObjectName("renameFlowAction")
        self.move_workflow_up_action = QAction("流程上移", self)
        self.move_workflow_up_action.setObjectName("moveWorkflowUpAction")
        self.move_workflow_down_action = QAction("流程下移", self)
        self.move_workflow_down_action.setObjectName("moveWorkflowDownAction")
        self.move_workflow_group_action = QAction("移动到组", self)
        self.move_workflow_group_action.setObjectName("moveWorkflowGroupAction")
        self.delete_flow_action = QAction("删除组/流程", self)
        self.delete_flow_action.setObjectName("deleteFlowAction")
        self.settings_action = QAction("设置", self)
        self.settings_action.setObjectName("projectSettingsAction")
        self.add_parallel_action = QAction("新增并行块", self)
        self.add_parallel_action.setObjectName("addParallelBlockAction")
        self.edit_parallel_action = QAction("编辑并行块", self)
        self.edit_parallel_action.setObjectName("editParallelBlockAction")
        self.delete_parallel_action = QAction("删除并行块", self)
        self.delete_parallel_action.setObjectName("deleteParallelBlockAction")
        self.copy_step_action = QAction("复制步骤", self)
        self.copy_step_action.setObjectName("copyStepAction")
        self.save_action.setEnabled(False)
        self.undo_action.setEnabled(False)
        self.start_action = QAction("启动", self)
        self.start_action.setObjectName("startWorkflowAction")
        self.pause_action = QAction("暂停", self)
        self.pause_action.setObjectName("pauseWorkflowAction")
        self.stop_action = QAction("停止", self)
        self.stop_action.setObjectName("stopWorkflowAction")
        self.record_action = QAction("录制", self)
        self.record_action.setObjectName("recordAction")
        self.record_pause_action = QAction("暂停录制", self)
        self.record_pause_action.setObjectName("pauseRecordingAction")
        self.record_pause_action.setEnabled(False)
        self.diagnostics_action = QAction("诊断", self)
        self.diagnostics_action.setObjectName("diagnosticsAction")
        self.run_step_action = QAction("单步运行", self)
        self.run_step_action.setObjectName("runSelectedStepAction")
        self.preview_action = QAction("预览条件", self)
        self.preview_action.setObjectName("previewConditionAction")
        for action in self.findChildren(QAction):
            icon_name = ACTION_ICON_NAMES.get(action.objectName())
            if icon_name is not None:
                action.setIcon(icon(icon_name))
        self.start_action.triggered.connect(self._start_selected_workflow)
        self.pause_action.triggered.connect(self._toggle_pause)
        self.stop_action.triggered.connect(self._stop_runtime)
        self.record_action.triggered.connect(self.recordRequested.emit)
        self.record_pause_action.triggered.connect(self.recordPauseRequested.emit)
        self.run_step_action.triggered.connect(self._run_selected_step)
        self.preview_action.triggered.connect(self._preview_selected_condition)
        self.diagnostics_action.triggered.connect(self.diagnostics_dialog.show)
        self.startup_group_combo.currentIndexChanged.connect(self._startup_group_changed)
        self.startup_workflow_combo.currentIndexChanged.connect(self._startup_workflow_changed)
        self.save_action.triggered.connect(self._save_project)
        self.undo_action.triggered.connect(self._undo_project_change)
        self.add_step_action.triggered.connect(self._add_step)
        self.add_template_step_action.triggered.connect(self._add_template_step)
        self.remove_step_action.triggered.connect(self._remove_selected_step)
        self.move_step_up_action.triggered.connect(lambda: self._move_selected_step(-1))
        self.move_step_down_action.triggered.connect(lambda: self._move_selected_step(1))
        self.add_group_action.triggered.connect(self._add_group)
        self.copy_group_action.triggered.connect(self._copy_selected_group)
        self.add_workflow_action.triggered.connect(self._add_workflow)
        self.copy_workflow_action.triggered.connect(self._copy_selected_workflow)
        self.copy_step_action.triggered.connect(self._copy_selected_step)
        self.rename_flow_action.triggered.connect(self._rename_selected_flow)
        self.move_workflow_up_action.triggered.connect(lambda: self._move_selected_workflow(-1))
        self.move_workflow_down_action.triggered.connect(lambda: self._move_selected_workflow(1))
        self.move_workflow_group_action.triggered.connect(self._move_workflow_to_group)
        self.delete_flow_action.triggered.connect(self._delete_selected_flow)
        self.settings_action.triggered.connect(self._edit_project_settings)
        self.add_parallel_action.triggered.connect(self._add_parallel_block)
        self.edit_parallel_action.triggered.connect(self._edit_selected_parallel_block)
        self.delete_parallel_action.triggered.connect(self._delete_parallel_block)
        self.startRequested.connect(self._start_selected_workflow)
        self.pauseRequested.connect(self._toggle_pause)
        self.stopRequested.connect(self._stop_runtime)
        self.run_view_model.stateChanged.connect(self._update_runtime_actions)
        self._build_workspace_columns()
        if self.runner_bridge is not None:
            self.runner_bridge.eventReceived.connect(self.run_view_model.consume)
            self.runner_bridge.eventReceived.connect(self.diagnostics_dialog.update_event)
            self.runner_bridge.eventReceived.connect(self.runtime_log_controller.consume)
            self.runner_bridge.failed.connect(self.statusBar().showMessage)
        self._refresh_startup_selectors()
        self._update_runtime_actions(self.run_view_model.state)
        self.setWindowTitle("Flow Runner[*]")
        self._refresh_save_state()
        self._refresh_undo_state()
        self._refresh_context_actions()
        self._apply_initial_window_geometry()
        self._restore_column_widths()
        self.workspace_splitter.splitterMoved.connect(self._column_widths_changed)

    def _build_workspace_columns(self) -> None:
        self.flow_controls = ResponsiveControlArea()
        runtime = self.flow_controls.add_group("运行")
        runtime.add_field("启动组", self.startup_group_combo, "startup_group")
        runtime.add_field("启动流程", self.startup_workflow_combo, "startup_workflow")
        for action in (
            self.start_action,
            self.pause_action,
            self.stop_action,
            self.record_action,
            self.record_pause_action,
        ):
            runtime.add_action(action)
        flows = self.flow_controls.add_group("组与流程")
        for action in (
            self.add_group_action,
            self.copy_group_action,
            self.add_workflow_action,
            self.copy_workflow_action,
            self.rename_flow_action,
            self.move_workflow_up_action,
            self.move_workflow_down_action,
            self.move_workflow_group_action,
            self.delete_flow_action,
        ):
            flows.add_action(action)
        parallel = self.flow_controls.add_group("并行监控")
        for action in (
            self.add_parallel_action,
            self.edit_parallel_action,
            self.delete_parallel_action,
        ):
            parallel.add_action(action)

        self.step_controls = ResponsiveControlArea()
        steps = self.step_controls.add_group("步骤")
        for action in (
            self.add_template_step_action,
            self.add_step_action,
            self.copy_step_action,
            self.remove_step_action,
            self.move_step_up_action,
            self.move_step_down_action,
            self.run_step_action,
            self.preview_action,
        ):
            steps.add_action(action)

        self.property_controls = ResponsiveControlArea()
        project = self.property_controls.add_group("项目")
        for action in (
            self.save_action,
            self.undo_action,
            self.settings_action,
            self.diagnostics_action,
        ):
            project.add_action(action)

        self.flow_column = ColumnContainer(
            self.flow_tree,
            self.flow_controls,
            object_name="flowColumn",
        )
        self.step_column = ColumnContainer(
            self.step_list,
            self.step_controls,
            object_name="stepColumn",
        )
        self.property_column = ColumnContainer(
            self.property_panel,
            self.property_controls,
            object_name="propertyColumn",
        )
        self.workspace_splitter.addWidget(self.flow_column)
        self.workspace_splitter.addWidget(self.step_column)
        self.workspace_splitter.addWidget(self.property_column)

    def _apply_initial_window_geometry(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            self.resize(self.window_preferences.size or QSize(1200, 800))
            return
        available = screen.availableGeometry()
        saved_size = self.window_preferences.size
        if saved_size is not None:
            size = _clamped_window_size(saved_size, available.size())
        else:
            size = QSize(
                min(available.width(), max(900, int(available.width() * 0.85))),
                min(available.height(), max(650, int(available.height() * 0.8))),
            )
        self.resize(size)
        self.move(available.center() - self.rect().center())

    def _restore_column_widths(self) -> None:
        widths = self._saved_column_widths
        if widths is not None:
            self.workspace_splitter.setSizes(list(widths))
        else:
            current = self.workspace_splitter.sizes()
            if len(current) == 3 and all(value > 0 for value in current):
                self._saved_column_widths = current[0], current[1], current[2]

    def _column_widths_changed(self, _position: int, _index: int) -> None:
        values = [max(1, value) for value in self.workspace_splitter.sizes()]
        if len(values) != 3:
            return
        widths = values[0], values[1], values[2]
        self._pending_column_widths = widths
        self._layout_dirty = widths != self._saved_column_widths
        self._refresh_save_state()
        self._refresh_undo_state()

    def _refresh_startup_selectors(self) -> None:
        project = self.view_model.project
        labels = ProjectDisplayIndex(project)
        configured_id = _uuid_setting(project.settings.get("entry_workflow_id"))
        selected_group_id: UUID | None = None
        selected_workflow_id: UUID | None = None
        for group in project.groups:
            for workflow in group.workflows:
                if workflow.id == configured_id:
                    selected_group_id = group.id
                    selected_workflow_id = workflow.id
                    break
            if selected_group_id is not None:
                break
        if selected_group_id is None:
            first_group = next((group for group in project.groups if group.workflows), None)
            if first_group is not None:
                selected_group_id = first_group.id
                selected_workflow_id = first_group.workflows[0].id

        blocked = self.startup_group_combo.blockSignals(True)
        try:
            self.startup_group_combo.clear()
            for group in project.groups:
                if group.workflows:
                    self.startup_group_combo.addItem(labels.group_label(group.id), group.id)
            index = self.startup_group_combo.findData(selected_group_id)
            self.startup_group_combo.setCurrentIndex(index)
        finally:
            self.startup_group_combo.blockSignals(blocked)
        self._populate_startup_workflows(selected_group_id, selected_workflow_id)

    def _populate_startup_workflows(
        self,
        group_id: UUID | None,
        selected_workflow_id: UUID | None = None,
    ) -> None:
        labels = ProjectDisplayIndex(self.view_model.project)
        blocked = self.startup_workflow_combo.blockSignals(True)
        try:
            self.startup_workflow_combo.clear()
            group = next(
                (group for group in self.view_model.project.groups if group.id == group_id),
                None,
            )
            if group is None:
                return
            for workflow in group.workflows:
                self.startup_workflow_combo.addItem(labels.workflow_label(workflow.id), workflow.id)
            index = self.startup_workflow_combo.findData(selected_workflow_id)
            self.startup_workflow_combo.setCurrentIndex(index if index >= 0 else 0)
        finally:
            self.startup_workflow_combo.blockSignals(blocked)

    def _startup_group_changed(self, _index: int) -> None:
        group_id = self.startup_group_combo.currentData()
        self._populate_startup_workflows(group_id if isinstance(group_id, UUID) else None)
        self._startup_workflow_changed(self.startup_workflow_combo.currentIndex())

    def _startup_workflow_changed(self, _index: int) -> None:
        workflow_id = self.startup_workflow_combo.currentData()
        if not isinstance(workflow_id, UUID):
            return
        settings = dict(self.view_model.project.settings)
        settings["entry_workflow_id"] = str(workflow_id)
        self.view_model.update_settings(settings)

    def _select_workflow(self, workflow_id: UUID) -> None:
        if not self._commit_pending_editor():
            self._restore_flow_selection()
            return
        workflow = self._workflow(workflow_id)
        self._group_id = self._group_for_workflow(workflow_id).id
        self._workflow_id = workflow.id
        self._parallel_block_id = None
        self.step_list.set_workflow(workflow)
        self._refresh_context_actions()

    def _select_group(self, group_id: UUID) -> None:
        if not self._commit_pending_editor():
            self._restore_flow_selection()
            return
        self._group_id = group_id
        self._workflow_id = None
        self._parallel_block_id = None
        self.step_list.set_workflow(Workflow(name="空"))
        self.property_panel.clear_step()
        self._refresh_context_actions()

    def _select_parallel_block(self, block_id: UUID) -> None:
        if not self._commit_pending_editor():
            self._restore_flow_selection()
            return
        self._parallel_block_id = block_id
        self._group_id = None
        self._workflow_id = None
        self.step_list.set_workflow(Workflow(name="空"))
        self.property_panel.clear_step()
        self._refresh_context_actions()

    def _select_step(self, step_id: UUID) -> None:
        if self._workflow_id is None:
            return
        previous_step_id = self.property_panel.step_id
        if not self._commit_pending_editor():
            if previous_step_id is not None:
                self.step_list.blockSignals(True)
                self.step_list.select_step(previous_step_id)
                self.step_list.blockSignals(False)
            return
        workflow = self._workflow(self._workflow_id)
        step = next(step for step in workflow.steps if step.id == step_id)
        self.property_panel.set_step(step)
        self._refresh_context_actions()

    def _commit_pending_editor(self) -> bool:
        if not self.property_panel.has_pending_edits:
            return True
        return self.property_panel.apply_pending() is not None

    def _restore_flow_selection(self) -> None:
        self.flow_tree.blockSignals(True)
        try:
            if self._workflow_id is not None:
                self.flow_tree.select_workflow(self._workflow_id)
            elif self._group_id is not None:
                self.flow_tree.select_group(self._group_id)
            elif self._parallel_block_id is not None:
                self.flow_tree.select_parallel_block(self._parallel_block_id)
        finally:
            self.flow_tree.blockSignals(False)

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

    def _undo_project_change(self) -> None:
        if self.property_panel.has_pending_edits:
            self.property_panel.discard_pending(self._selected_project_step())
            self._reload_selection_from_project()
            self._refresh_save_state()
            self._refresh_undo_state()
            return
        if self._layout_dirty:
            self.workspace_splitter.blockSignals(True)
            try:
                self._restore_column_widths()
            finally:
                self.workspace_splitter.blockSignals(False)
            self._pending_column_widths = None
            self._layout_dirty = False
            self._refresh_save_state()
            self._refresh_undo_state()
            return
        self.view_model.undo()
        self._refresh_save_state()
        self._refresh_undo_state()

    def _selected_project_step(self) -> AutomationStep | None:
        if self._workflow_id is None or self.property_panel.step_id is None:
            return None
        try:
            workflow = self._workflow(self._workflow_id)
        except KeyError:
            return None
        return next(
            (step for step in workflow.steps if step.id == self.property_panel.step_id),
            None,
        )

    def _project_changed(self, _project: Project) -> None:
        self.runtime_formatter.set_project(_project)
        self._refresh_startup_selectors()
        self._reload_selection_from_project()
        self._refresh_save_state()
        self._refresh_undo_state()

    def _restore_flow_group_expansion(self) -> None:
        project_id = self.view_model.project.id
        stored = self.flow_tree_preferences.collapsed_groups(project_id)
        valid = self.flow_tree.restore_collapsed_groups(stored)
        if valid != stored:
            self.flow_tree_preferences.set_collapsed_groups(project_id, valid)

    def _flow_group_expansion_changed(self, _group_id: UUID, _expanded: bool) -> None:
        self.flow_tree_preferences.set_collapsed_groups(
            self.view_model.project.id,
            self.flow_tree.collapsed_group_ids(),
        )

    def _reload_selection_from_project(self) -> None:
        project = self.view_model.project
        selected_step_id = self.property_panel.step_id
        self.property_panel.set_project(project)
        self.flow_tree.blockSignals(True)
        self.step_list.blockSignals(True)
        try:
            self.flow_tree.set_project(project)
            self._restore_flow_group_expansion()
            if self._parallel_block_id is not None:
                try:
                    self.flow_tree.select_parallel_block(self._parallel_block_id)
                except KeyError:
                    self._parallel_block_id = None
                else:
                    self._group_id = None
                    self._workflow_id = None
                    self.step_list.set_workflow(Workflow(name="空"))
                    self.property_panel.clear_step()
                    return
            if self._workflow_id is not None:
                try:
                    workflow = self._workflow(self._workflow_id)
                except KeyError:
                    self._workflow_id = None
                else:
                    self._group_id = self._group_for_workflow(workflow.id).id
                    self._parallel_block_id = None
                    self.flow_tree.select_workflow(workflow.id)
                    self.step_list.set_workflow(workflow)
                    selected_step = next(
                        (step for step in workflow.steps if step.id == selected_step_id),
                        None,
                    )
                    if selected_step is None:
                        self.property_panel.clear_step()
                    else:
                        self.step_list.select_step(selected_step.id)
                        self.property_panel.set_step(selected_step)
                    return
            if self._group_id is not None:
                try:
                    self.flow_tree.select_group(self._group_id)
                except KeyError:
                    self._group_id = None
                else:
                    self._workflow_id = None
                    self._parallel_block_id = None
                    self.step_list.set_workflow(Workflow(name="空"))
                    self.property_panel.clear_step()
                    return
            self.step_list.set_workflow(Workflow(name="空"))
            self.property_panel.clear_step()
        finally:
            self.flow_tree.blockSignals(False)
            self.step_list.blockSignals(False)
            self._refresh_context_actions()

    def _history_changed(self, _can_undo: bool) -> None:
        self._refresh_undo_state()

    def _pending_changed(self, _pending: bool) -> None:
        self._refresh_save_state()
        self._refresh_undo_state()

    def _refresh_undo_state(self) -> None:
        self.undo_action.setEnabled(
            self.property_panel.has_pending_edits or self._layout_dirty or self.view_model.can_undo
        )

    def _refresh_save_state(self) -> None:
        modified = (
            self.view_model.dirty or self.property_panel.has_pending_edits or self._layout_dirty
        )
        self.save_action.setEnabled(self.save_project is not None and modified)
        self.setWindowModified(modified)

    def _refresh_context_actions(self) -> None:
        self.copy_group_action.setEnabled(self._group_id is not None and self._workflow_id is None)
        self.copy_workflow_action.setEnabled(self._workflow_id is not None)
        selected_step = self._selected_project_step()
        self.copy_step_action.setEnabled(selected_step is not None)
        self.edit_parallel_action.setEnabled(self._parallel_block_id is not None)

    def _save_project(self) -> bool:
        if self.save_project is None:
            self.statusBar().showMessage("未配置项目保存服务")
            return False
        if self.property_panel.has_pending_edits:
            if self.property_panel.apply_pending() is None:
                detail = self.property_panel.validation_error or "请修正当前步骤中的参数"
                self.statusBar().showMessage(f"项目保存失败：{detail}")
                return False
        if self._layout_dirty and self._pending_column_widths is not None:
            settings = dict(self.view_model.project.settings)
            ui_layout = dict(settings.get("ui_layout", {}))
            ui_layout["column_widths"] = list(self._pending_column_widths)
            settings["ui_layout"] = ui_layout
            self.view_model.update_settings(settings)
        try:
            self.save_project(self.view_model.project)
        except Exception as error:
            self.statusBar().showMessage(f"项目保存失败：{error}")
            return False
        self.view_model.mark_saved()
        if self._pending_column_widths is not None:
            self._saved_column_widths = self._pending_column_widths
        self._pending_column_widths = None
        self._layout_dirty = False
        self._refresh_save_state()
        timestamp = datetime.now().strftime("%H:%M:%S")
        location = f"：{self.project_path}" if self.project_path is not None else ""
        runtime_note = (
            "；当前运行不受影响，下次启动生效"
            if self.run_view_model.state in {RunnerState.RUNNING, RunnerState.PAUSED}
            else ""
        )
        self.statusBar().showMessage(f"项目已保存{location}（{timestamp}）{runtime_note}")
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

    def _add_template_step(self) -> None:
        if self._workflow_id is None:
            self.statusBar().showMessage("请先选择要添加步骤的流程")
            return
        step = self.create_template_step()
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
        dialog = GuidedAddDialog(
            self.registry,
            self.view_model.project,
            current_workflow_id=self._workflow_id,
            region_capture=self.region_capture,
            point_capture=self.point_capture,
        )
        if dialog.exec() != GuidedAddDialog.DialogCode.Accepted:
            return None
        return dialog.step()

    def _prompt_template_step(self) -> AutomationStep | None:
        if self._workflow_id is None:
            return None
        dialog = TemplateStepDialog(
            self.view_model.project,
            current_workflow_id=self._workflow_id,
        )
        if dialog.exec() != TemplateStepDialog.DialogCode.Accepted:
            return None
        return dialog.step()

    def _add_group(self) -> None:
        name = self.request_name("group", "")
        if not name:
            return
        group = FlowGroup(name=name)
        self.view_model.add_group(group)
        self.flow_tree.select_group(group.id)

    def _copy_selected_group(self) -> None:
        if self._group_id is None or self._workflow_id is not None:
            self.statusBar().showMessage("请先选择要复制的流程组")
            return
        copied = self.view_model.copy_group(self._group_id)
        self.flow_tree.select_group(copied.id)

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

    def _copy_selected_workflow(self) -> None:
        if self._group_id is None or self._workflow_id is None:
            self.statusBar().showMessage("请先选择要复制的流程")
            return
        copied = self.view_model.copy_workflow(self._group_id, self._workflow_id)
        self.flow_tree.select_workflow(copied.id)

    def _copy_selected_step(self) -> None:
        if self._workflow_id is None or self.property_panel.step_id is None:
            self.statusBar().showMessage("请先选择要复制的步骤")
            return
        copied = self.view_model.copy_step(
            self._workflow_id,
            self.property_panel.step_id,
        )
        self.step_list.select_step(copied.id)

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

    def _move_selected_workflow(self, direction: int) -> None:
        if self._workflow_id is None:
            self.statusBar().showMessage("请先选择要移动的流程")
            return
        self.view_model.move_workflow(self._workflow_id, direction)

    def _move_workflow_to_group(self) -> None:
        if self._workflow_id is None:
            self.statusBar().showMessage("请先选择要移动的流程")
            return
        target_group_id = self.select_group_target(
            self.view_model.project,
            self._workflow_id,
        )
        if target_group_id is None:
            return
        self.view_model.move_workflow_to_group(self._workflow_id, target_group_id)

    def _prompt_workflow_group(
        self,
        project: Project,
        workflow_id: UUID,
    ) -> UUID | None:
        current_group = self._group_for_workflow(workflow_id)
        choices = [group for group in project.groups if group.id != current_group.id]
        if not choices:
            self.statusBar().showMessage("没有其它可移动到的流程组")
            return None
        display = ProjectDisplayIndex(project)
        labels = [display.group_label(group.id) for group in choices]
        selected, accepted = QInputDialog.getItem(
            self,
            "移动流程",
            "目标流程组",
            labels,
            0,
            False,
        )
        if not accepted:
            return None
        return choices[labels.index(selected)].id

    def _delete_selected_flow(self) -> None:
        if self._workflow_id is not None:
            workflow = self._workflow(self._workflow_id)
            dependencies = [
                block.name
                for block in self.view_model.project.parallel_blocks
                if workflow.id in block.workflow_ids
            ]
            if dependencies:
                self.statusBar().showMessage(
                    f"流程“{workflow.name}”仍被并行监控块引用："
                    f"{'、'.join(dependencies)}；请先编辑或删除这些并行块"
                )
                return
            reference_count = self.view_model.workflow_route_reference_count(workflow.id)
            cleanup_note = f"，并同时删除 {reference_count} 条引用路由" if reference_count else ""
            if self.confirm_delete(f"流程“{workflow.name}”{cleanup_note}"):
                removed_routes = self.view_model.remove_workflow(workflow.id)
                self._workflow_id = None
                self._refresh_context_actions()
                self.statusBar().showMessage(
                    f"已删除流程“{workflow.name}”并清理 {removed_routes} 条引用路由"
                )
            return
        if self._group_id is not None:
            group = next(
                group for group in self.view_model.project.groups if group.id == self._group_id
            )
            if self.confirm_delete(f"流程组“{group.name}”"):
                self.view_model.remove_group(group.id)
                self._group_id = None
                self._refresh_context_actions()
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
        previous_hotkeys = HotkeyConfig.model_validate(
            self.view_model.project.settings.get("hotkeys", {})
        )
        updated_hotkeys = HotkeyConfig.model_validate(settings.get("hotkeys", {}))
        self.view_model.update_settings(settings)
        self.statusBar().showMessage("设置已更新；OCR 引擎将在下次启动时生效")
        if updated_hotkeys != previous_hotkeys:
            self.hotkeyConfigChanged.emit(updated_hotkeys)

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

    def _edit_selected_parallel_block(self) -> None:
        if self._parallel_block_id is None:
            self.statusBar().showMessage("请先选择并行监控块")
            return
        block = next(
            block
            for block in self.view_model.project.parallel_blocks
            if block.id == self._parallel_block_id
        )
        updated = self.edit_parallel_block(block)
        if updated is None:
            return
        self.view_model.update_parallel_block(updated)
        self.flow_tree.select_parallel_block(updated.id)

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
            self._refresh_context_actions()

    def _prompt_parallel_block(self) -> ParallelBlock | None:
        dialog = ParallelBlockDialog(self.view_model.project)
        if dialog.exec() != ParallelBlockDialog.DialogCode.Accepted:
            return None
        return dialog.block()

    def _prompt_edit_parallel_block(self, block: ParallelBlock) -> ParallelBlock | None:
        dialog = ParallelBlockDialog(self.view_model.project, block)
        if dialog.exec() != ParallelBlockDialog.DialogCode.Accepted:
            return None
        return dialog.block()

    def _start_selected_workflow(self) -> None:
        if self.runner_bridge is None:
            self.statusBar().showMessage("运行服务尚未配置")
            return
        if self._parallel_block_id is not None:
            accepted = self.runner_bridge.start_parallel(
                self.view_model.project,
                self._parallel_block_id,
            )
        else:
            workflow_id = self.startup_workflow_combo.currentData()
            if not isinstance(workflow_id, UUID):
                self.statusBar().showMessage("请先配置要启动的流程")
                return
            accepted = self.runner_bridge.start(self.view_model.project, workflow_id)
        if accepted and self.view_model.project.settings.get("minimize_on_workflow_start") is True:
            self.showMinimized()

    def _toggle_pause(self) -> None:
        if self.runner_bridge is None:
            return
        if self.run_view_model.state is RunnerState.PAUSED:
            if self.runner_bridge.resume():
                self.runtimePauseChanged.emit(False)
        else:
            if self.runner_bridge.pause():
                self.runtimePauseChanged.emit(True)

    def _run_selected_step(self) -> None:
        if (
            self.runner_bridge is None
            or self._workflow_id is None
            or self.property_panel.step_id is None
        ):
            self.statusBar().showMessage("请先选择要运行的步骤")
            return
        self.runner_bridge.run_step(
            self.view_model.project,
            self._workflow_id,
            self.property_panel.step_id,
        )

    def _preview_selected_condition(self) -> None:
        if (
            self.runner_bridge is None
            or self._workflow_id is None
            or self.property_panel.step_id is None
        ):
            self.statusBar().showMessage("请先选择要预览的检测步骤")
            return
        self.runner_bridge.preview_condition(
            self.view_model.project,
            self._workflow_id,
            self.property_panel.step_id,
        )

    def _stop_runtime(self) -> None:
        if self.runner_bridge is not None and self.runner_bridge.stop():
            self.runtimeStopAccepted.emit()

    def _update_runtime_actions(self, state: RunnerState) -> None:
        active = state in {RunnerState.RUNNING, RunnerState.PAUSED}
        self.start_action.setEnabled(not active)
        self.pause_action.setEnabled(active)
        self.stop_action.setEnabled(active)
        self.run_step_action.setEnabled(not active)
        self.preview_action.setEnabled(not active)
        self.pause_action.setText("继续" if state is RunnerState.PAUSED else "暂停")
        self.pause_action.setIcon(icon("resume" if state is RunnerState.PAUSED else "pause"))

    def closeEvent(self, event: QCloseEvent) -> None:
        modified = (
            self.view_model.dirty or self.property_panel.has_pending_edits or self._layout_dirty
        )
        running = self.runner_bridge is not None and self.runner_bridge.is_running
        if modified or running:
            decision = (
                self._request_close_decision(modified=modified, running=running)
                if self.isVisible() or self._confirm_close_injected
                else _hidden_close_decision(modified=modified, running=running)
            )
        else:
            decision = CloseDecision.CLOSE

        if decision is CloseDecision.CANCEL:
            event.ignore()
            return
        if _requires_save(decision) and not self._save_project():
            event.ignore()
            return
        if _requires_stop(decision):
            if self.runner_bridge is None or not self.runner_bridge.shutdown():
                self.statusBar().showMessage("任务未能停止，窗口保持打开")
                event.ignore()
                return
        super().closeEvent(event)
        if event.isAccepted():
            size = self.normalGeometry().size() if self.isMaximized() else self.size()
            self.window_preferences.size = size

    def set_recording_state(self, recording: bool, *, paused: bool = False) -> None:
        self.record_action.setText("停止录制" if recording else "录制")
        self.record_action.setProperty("status", "recording" if recording else "idle")
        self.record_pause_action.setEnabled(recording)
        self.record_pause_action.setText("继续录制" if recording and paused else "暂停录制")
        self.record_pause_action.setIcon(icon("resume" if recording and paused else "pause"))

    def _request_close_decision(self, *, modified: bool, running: bool) -> CloseDecision:
        if self._confirm_close_accepts_state:
            decision = self.confirm_close(modified=modified, running=running)
        else:
            decision = self.confirm_close()
        return _normalize_close_decision(decision, running=running)

    def _confirm_close(self, *, modified: bool, running: bool) -> CloseDecision:
        dialog = CloseConfirmationDialog(
            modified=modified,
            running=running,
            parent=self,
        )
        dialog.exec()
        return dialog.decision


def _accepts_close_state(callback: Callable[..., object]) -> bool:
    try:
        signature(callback).bind(modified=False, running=False)
    except (TypeError, ValueError):
        return False
    return True


def _clamped_window_size(requested: QSize, available: QSize) -> QSize:
    minimum_width = min(640, available.width())
    minimum_height = min(480, available.height())
    return QSize(
        max(minimum_width, min(requested.width(), available.width())),
        max(minimum_height, min(requested.height(), available.height())),
    )


def _uuid_setting(value: object) -> UUID | None:
    if isinstance(value, UUID):
        return value
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _column_widths_from_settings(settings: dict[str, object]) -> tuple[int, int, int] | None:
    ui_layout = settings.get("ui_layout")
    if not isinstance(ui_layout, dict):
        return None
    widths = ui_layout.get("column_widths")
    if (
        not isinstance(widths, list)
        or len(widths) != 3
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in widths
        )
    ):
        return None
    return widths[0], widths[1], widths[2]


def _normalize_close_decision(
    decision: CloseDecision | str,
    *,
    running: bool,
) -> CloseDecision:
    if isinstance(decision, CloseDecision):
        return decision
    legacy = {
        "save": (CloseDecision.SAVE_STOP_AND_CLOSE if running else CloseDecision.SAVE_AND_CLOSE),
        "discard": (
            CloseDecision.DISCARD_STOP_AND_CLOSE if running else CloseDecision.DISCARD_AND_CLOSE
        ),
        "cancel": CloseDecision.CANCEL,
    }
    if decision in legacy:
        return legacy[decision]
    return CloseDecision(decision)


def _hidden_close_decision(*, modified: bool, running: bool) -> CloseDecision:
    if modified and running:
        return CloseDecision.DISCARD_STOP_AND_CLOSE
    if modified:
        return CloseDecision.DISCARD_AND_CLOSE
    if running:
        return CloseDecision.STOP_AND_CLOSE
    return CloseDecision.CLOSE


def _requires_save(decision: CloseDecision) -> bool:
    return decision in {
        CloseDecision.SAVE_AND_CLOSE,
        CloseDecision.SAVE_STOP_AND_CLOSE,
    }


def _requires_stop(decision: CloseDecision) -> bool:
    return decision in {
        CloseDecision.STOP_AND_CLOSE,
        CloseDecision.SAVE_STOP_AND_CLOSE,
        CloseDecision.DISCARD_STOP_AND_CLOSE,
    }

import json
from collections.abc import Callable
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
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from flow_runner.capabilities.registry import CapabilityRegistry
from flow_runner.domain.conditions import ConditionNode
from flow_runner.domain.errors import FlowRunnerError
from flow_runner.domain.project import AutomationStep, Project
from flow_runner.ui.capture_preferences import CapturePreferences
from flow_runner.ui.editor_preferences import EditorPreferences
from flow_runner.ui.editors.action_editor import ActionEditor
from flow_runner.ui.editors.condition_editor import ConditionEditor
from flow_runner.ui.editors.policy_editor import PolicyEditor
from flow_runner.ui.editors.route_editor import RouteEditor
from flow_runner.ui.region_capture import PointCaptureService, RegionCaptureService
from flow_runner.ui.result_bindings import result_binding_options


class PropertyPanel(QScrollArea):
    stepChanged = Signal(object)
    validationFailed = Signal(str)
    pendingChanged = Signal(bool)

    def __init__(
        self,
        registry: CapabilityRegistry | None = None,
        project: Project | None = None,
        *,
        apply_step: Callable[[AutomationStep], None] | None = None,
        editor_preferences: EditorPreferences | None = None,
        region_capture: RegionCaptureService | None = None,
        point_capture: PointCaptureService | None = None,
        capture_preferences: CapturePreferences | None = None,
    ) -> None:
        super().__init__()
        self.setObjectName("propertyPanel")
        self.step_id: UUID | None = None
        self._step: AutomationStep | None = None
        self._loading = False
        self._pending = False
        self._validation_error = ""
        self._switching_mode = False
        self.apply_step = apply_step
        self.editor_preferences = editor_preferences or EditorPreferences()
        self.capture_preferences = capture_preferences or CapturePreferences()
        show_advanced = self.editor_preferences.show_advanced
        self._condition_json_baseline = ""
        self._actions_json_baseline = ""
        self._routes_json_baseline = ""
        self._condition_policy_json_baseline = ""
        self._action_policy_json_baseline = ""
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
        self.show_advanced_check = QCheckBox("显示高级参数")
        self.show_advanced_check.setObjectName("showAdvancedFields")
        self.show_advanced_check.setChecked(show_advanced)
        self.action_editor = (
            ActionEditor(
                registry,
                show_advanced=show_advanced,
                pick_point=(
                    (lambda target: point_capture.pick_point(target, self))
                    if point_capture is not None
                    else None
                ),
            )
            if registry is not None
            else None
        )
        self.condition_editor = (
            ConditionEditor(
                registry,
                show_advanced=show_advanced,
                region_capture=region_capture,
            )
            if registry is not None
            else None
        )
        self.route_editor = RouteEditor(project) if registry is not None else None
        self.policy_editor = PolicyEditor(registry, show_advanced=show_advanced)
        self.apply_button = QPushButton("应用")
        self.apply_button.setObjectName("applyStepButton")
        self.setWidgetResizable(True)
        self.content = QWidget()
        self.content.setObjectName("propertyPanelContent")
        self.setWidget(self.content)
        layout = QVBoxLayout(self.content)
        layout.addWidget(self.title)
        self.mode_tabs = QTabWidget()
        self.mode_tabs.setObjectName("propertyModeTabs")
        self.common_tab = QWidget()
        self.common_tab.setObjectName("commonPropertyTab")
        common_layout = QVBoxLayout(self.common_tab)
        self.hide_during_capture_check = QCheckBox("框选时隐藏程序界面")
        self.hide_during_capture_check.setObjectName("hideDuringCapture")
        self.hide_during_capture_check.setChecked(self.capture_preferences.hide_application)
        common_layout.addWidget(self.hide_during_capture_check)
        common_layout.addWidget(self.show_advanced_check)
        common_form = QFormLayout()
        common_form.addRow("名称", self.name_edit)
        common_form.addRow("状态", self.enabled_check)
        if self.condition_editor is not None:
            common_form.addRow("条件引导", self.condition_editor)
        if self.action_editor is not None:
            common_form.addRow("动作引导", self.action_editor)
        common_form.addRow("策略引导", self.policy_editor)
        if self.route_editor is not None:
            common_form.addRow("路由引导", self.route_editor)
        common_layout.addLayout(common_form)
        common_layout.addStretch()
        self.advanced_json_tab = QWidget()
        self.advanced_json_tab.setObjectName("advancedJsonTab")
        advanced_form = QFormLayout(self.advanced_json_tab)
        advanced_form.addRow("条件 JSON", self.condition_edit)
        advanced_form.addRow("动作 JSON", self.actions_edit)
        advanced_form.addRow("检测策略 JSON", self.condition_policy_edit)
        advanced_form.addRow("动作策略 JSON", self.action_policy_edit)
        advanced_form.addRow("路由 JSON", self.routes_edit)
        self.mode_tabs.addTab(self.common_tab, "常用配置")
        self.mode_tabs.addTab(self.advanced_json_tab, "高级 JSON")
        layout.addWidget(self.mode_tabs)
        layout.addWidget(self.apply_button)
        layout.addStretch()
        self.apply_button.clicked.connect(self._apply)
        self.mode_tabs.currentChanged.connect(self._mode_changed)
        self.show_advanced_check.toggled.connect(self._advanced_visibility_changed)
        self.hide_during_capture_check.toggled.connect(self._capture_visibility_changed)
        self.name_edit.textChanged.connect(self._mark_pending)
        self.enabled_check.toggled.connect(self._mark_pending)
        for editor in (
            self.condition_edit,
            self.actions_edit,
            self.condition_policy_edit,
            self.action_policy_edit,
            self.routes_edit,
        ):
            editor.textChanged.connect(self._mark_pending)
        self.policy_editor.changed.connect(self._mark_pending)
        if self.action_editor is not None:
            self.action_editor.changed.connect(self._mark_pending)
        if self.condition_editor is not None:
            self.condition_editor.changed.connect(self._condition_changed)
        if self.route_editor is not None:
            self.route_editor.changed.connect(self._mark_pending)

    def _advanced_visibility_changed(self, visible: bool) -> None:
        self.editor_preferences.show_advanced = visible
        if self.condition_editor is not None:
            self.condition_editor.set_advanced_visible(visible)
        if self.action_editor is not None:
            self.action_editor.set_advanced_visible(visible)
        self.policy_editor.set_advanced_visible(visible)

    def _capture_visibility_changed(self, hidden: bool) -> None:
        self.capture_preferences.hide_application = hidden

    def _condition_changed(self) -> None:
        self._mark_pending()
        if self.condition_editor is not None:
            self._refresh_binding_options(self.condition_editor.condition_for_bindings())

    def _refresh_binding_options(self, condition: ConditionNode | None) -> None:
        options = result_binding_options(condition)
        if self.action_editor is not None:
            self.action_editor.set_binding_options(options)
        if self.route_editor is not None:
            self.route_editor.set_binding_options(options)

    def _mode_changed(self, _index: int) -> None:
        if self._loading or self._switching_mode or self._step is None:
            return
        if self.mode_tabs.currentWidget() is self.advanced_json_tab:
            if not self._sync_guided_to_json():
                self._restore_mode(self.common_tab)
            return
        if not self._sync_json_to_guided():
            self._restore_mode(self.advanced_json_tab)

    def _restore_mode(self, tab: QWidget) -> None:
        self._switching_mode = True
        self.mode_tabs.setCurrentWidget(tab)
        self._switching_mode = False

    def _sync_guided_to_json(self) -> bool:
        try:
            step = self._step_from_guided()
        except (ValueError, KeyError, FlowRunnerError) as error:
            self._set_validation_error(error)
            return False
        self._set_json_editors(step)
        self._refresh_binding_options(step.condition)
        self._validation_error = ""
        return True

    def _sync_json_to_guided(self) -> bool:
        try:
            step = self._step_from_json()
        except (ValueError, KeyError, FlowRunnerError) as error:
            self._set_validation_error(error)
            return False
        self._loading = True
        if self.condition_editor is not None:
            self.condition_editor.set_condition(step.condition)
        self._refresh_binding_options(step.condition)
        if self.action_editor is not None:
            self.action_editor.set_actions(step.actions)
        self.policy_editor.set_policies(step.condition_policy, step.action_policy)
        if self.route_editor is not None:
            self.route_editor.set_routes(step.routes)
        self._loading = False
        self._set_json_baselines()
        self._validation_error = ""
        return True

    def _step_from_guided(self) -> AutomationStep:
        assert self._step is not None
        if self.action_editor is not None:
            self.action_editor.commit_pending()
        if self.route_editor is not None:
            self.route_editor.commit_pending()
        condition_policy, action_policy = self.policy_editor.policies()
        return AutomationStep.model_validate(
            {
                "id": self._step.id,
                "name": self.name_edit.text(),
                "enabled": self.enabled_check.isChecked(),
                "condition": (
                    self.condition_editor.condition()
                    if self.condition_editor is not None
                    else json.loads(self.condition_edit.toPlainText())
                ),
                "actions": (
                    self.action_editor.action_specs()
                    if self.action_editor is not None
                    else json.loads(self.actions_edit.toPlainText())
                ),
                "condition_policy": condition_policy,
                "action_policy": action_policy,
                "routes": (
                    self.route_editor.routes()
                    if self.route_editor is not None
                    else json.loads(self.routes_edit.toPlainText())
                ),
            }
        )

    def _step_from_json(self) -> AutomationStep:
        assert self._step is not None
        return AutomationStep.model_validate(
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

    def _set_json_editors(self, step: AutomationStep) -> None:
        previous_loading = self._loading
        self._loading = True
        self.condition_edit.setPlainText(_json(step.condition))
        self.actions_edit.setPlainText(_json(step.actions))
        self.condition_policy_edit.setPlainText(_json(step.condition_policy))
        self.action_policy_edit.setPlainText(_json(step.action_policy))
        self.routes_edit.setPlainText(_json(step.routes))
        self._set_json_baselines()
        self._loading = previous_loading

    def _set_json_baselines(self) -> None:
        self._condition_json_baseline = self.condition_edit.toPlainText()
        self._actions_json_baseline = self.actions_edit.toPlainText()
        self._condition_policy_json_baseline = self.condition_policy_edit.toPlainText()
        self._action_policy_json_baseline = self.action_policy_edit.toPlainText()
        self._routes_json_baseline = self.routes_edit.toPlainText()

    def _set_validation_error(self, error: Exception) -> None:
        self._validation_error = str(error)
        self.validationFailed.emit(self._validation_error)

    @property
    def has_pending_edits(self) -> bool:
        return self._pending

    @property
    def validation_error(self) -> str:
        return self._validation_error

    def _mark_pending(self) -> None:
        if self._loading or self._step is None or self._pending:
            return
        self._pending = True
        self.pendingChanged.emit(True)

    def _clear_pending(self) -> None:
        changed = self._pending
        self._pending = False
        if changed:
            self.pendingChanged.emit(False)

    def set_step(self, step: AutomationStep) -> None:
        self._loading = True
        self._validation_error = ""
        self.step_id = step.id
        self._step = step
        self.title.setText(step.name)
        self.name_edit.setText(step.name)
        self.enabled_check.setChecked(step.enabled)
        self._condition_json_baseline = _json(step.condition)
        self.condition_edit.setPlainText(self._condition_json_baseline)
        if self.condition_editor is not None:
            self.condition_editor.set_condition(step.condition)
        self._refresh_binding_options(step.condition)
        self._actions_json_baseline = _json(step.actions)
        self.actions_edit.setPlainText(self._actions_json_baseline)
        if self.action_editor is not None:
            self.action_editor.set_actions(step.actions)
        self._condition_policy_json_baseline = _json(step.condition_policy)
        self.condition_policy_edit.setPlainText(self._condition_policy_json_baseline)
        self._action_policy_json_baseline = _json(step.action_policy)
        self.action_policy_edit.setPlainText(self._action_policy_json_baseline)
        self.policy_editor.set_policies(step.condition_policy, step.action_policy)
        self._routes_json_baseline = _json(step.routes)
        self.routes_edit.setPlainText(self._routes_json_baseline)
        if self.route_editor is not None:
            self.route_editor.set_step_context(step.id)
            self.route_editor.set_routes(step.routes)
        self._loading = False
        self._clear_pending()

    def clear_step(self) -> None:
        self._loading = True
        self._validation_error = ""
        self.step_id = None
        self._step = None
        if self.route_editor is not None:
            self.route_editor.set_step_context(None)
        self._refresh_binding_options(None)
        self.title.clear()
        self.name_edit.clear()
        self.enabled_check.setChecked(False)
        for editor in (
            self.condition_edit,
            self.actions_edit,
            self.condition_policy_edit,
            self.action_policy_edit,
            self.routes_edit,
        ):
            editor.clear()
        self._loading = False
        self._clear_pending()

    def discard_pending(self, step: AutomationStep | None) -> None:
        if step is None:
            self.clear_step()
        else:
            self.set_step(step)

    def set_project(self, project: Project) -> None:
        if self.route_editor is not None:
            self.route_editor.set_project(project)

    def apply_pending(self) -> AutomationStep | None:
        if self._step is None:
            return None
        self._validation_error = ""
        try:
            if (
                self.action_editor is not None
                and self.actions_edit.toPlainText() == self._actions_json_baseline
            ):
                self.action_editor.commit_pending()
            if (
                self.route_editor is not None
                and self.routes_edit.toPlainText() == self._routes_json_baseline
            ):
                self.route_editor.commit_pending()
            guided_condition_policy, guided_action_policy = self.policy_editor.policies()
            step = AutomationStep.model_validate(
                {
                    "id": self._step.id,
                    "name": self.name_edit.text(),
                    "enabled": self.enabled_check.isChecked(),
                    "condition": (
                        self.condition_editor.condition()
                        if self.condition_editor is not None
                        and self.condition_edit.toPlainText() == self._condition_json_baseline
                        else json.loads(self.condition_edit.toPlainText())
                    ),
                    "actions": (
                        self.action_editor.action_specs()
                        if self.action_editor is not None
                        and self.actions_edit.toPlainText() == self._actions_json_baseline
                        else json.loads(self.actions_edit.toPlainText())
                    ),
                    "condition_policy": (
                        guided_condition_policy
                        if self.condition_policy_edit.toPlainText()
                        == self._condition_policy_json_baseline
                        else json.loads(self.condition_policy_edit.toPlainText())
                    ),
                    "action_policy": (
                        guided_action_policy
                        if self.action_policy_edit.toPlainText()
                        == self._action_policy_json_baseline
                        else json.loads(self.action_policy_edit.toPlainText())
                    ),
                    "routes": (
                        self.route_editor.routes()
                        if self.route_editor is not None
                        and self.routes_edit.toPlainText() == self._routes_json_baseline
                        else json.loads(self.routes_edit.toPlainText())
                    ),
                }
            )
            if self.apply_step is not None:
                self.apply_step(step)
        except (ValueError, KeyError, FlowRunnerError) as error:
            self._validation_error = str(error)
            self.validationFailed.emit(self._validation_error)
            return None
        self.set_step(step)
        self.stepChanged.emit(step)
        return step

    def _apply(self) -> None:
        self.apply_pending()


def _json(value: object) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    elif isinstance(value, list):
        value = [
            item.model_dump(mode="json") if isinstance(item, BaseModel) else item for item in value
        ]
    return json.dumps(value, ensure_ascii=False, indent=2)

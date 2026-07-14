from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFormLayout, QLabel, QWidget

from flow_runner.capabilities.registry import CapabilityRegistry
from flow_runner.domain.enums import ConditionMode
from flow_runner.domain.policies import ActionPolicy, ConditionPolicy
from flow_runner.ui.editors.action_editor import ActionEditor
from flow_runner.ui.widgets import (
    FocusWheelComboBox,
    FocusWheelDoubleSpinBox,
    FocusWheelSpinBox,
)


class PolicyEditor(QWidget):
    changed = Signal()

    def __init__(
        self,
        registry: CapabilityRegistry | None = None,
        *,
        show_advanced: bool = False,
    ) -> None:
        super().__init__()
        self._loading = False
        self._show_advanced = show_advanced
        self.summary_label = QLabel()
        self.summary_label.setObjectName("policySummary")
        self.summary_label.setWordWrap(True)
        self.mode_combo = FocusWheelComboBox()
        self.mode_combo.addItem("检查一次", ConditionMode.ONCE)
        self.mode_combo.addItem("等待满足", ConditionMode.UNTIL)
        self.interval_spin = FocusWheelDoubleSpinBox()
        self.interval_spin.setRange(0.0, 1_000_000.0)
        self.interval_spin.setDecimals(3)
        self.max_attempts_spin = FocusWheelSpinBox()
        self.max_attempts_spin.setRange(0, 1_000_000)
        self.max_attempts_spin.setSpecialValueText("无限")
        self.timeout_spin = FocusWheelDoubleSpinBox()
        self.timeout_spin.setRange(0.0, 1_000_000.0)
        self.timeout_spin.setDecimals(3)
        self.timeout_spin.setSpecialValueText("无")
        self.action_attempts_spin = FocusWheelSpinBox()
        self.action_attempts_spin.setRange(1, 1_000_000)
        self.action_retry_spin = FocusWheelDoubleSpinBox()
        self.action_retry_spin.setRange(0.0, 1_000_000.0)
        self.action_retry_spin.setDecimals(3)
        self._condition_policy = ConditionPolicy()
        self._action_policy = ActionPolicy()
        self.before_actions_editor = (
            ActionEditor(registry, show_advanced=show_advanced) if registry is not None else None
        )
        self.after_no_match_actions_editor = (
            ActionEditor(registry, show_advanced=show_advanced) if registry is not None else None
        )
        self.form_layout = QFormLayout(self)
        self.form_layout.addRow("策略摘要", self.summary_label)
        self.form_layout.addRow("检测模式", self.mode_combo)
        self.form_layout.addRow("轮询间隔（秒）", self.interval_spin)
        self.form_layout.addRow("最大检测次数", self.max_attempts_spin)
        self.form_layout.addRow("检测超时（秒）", self.timeout_spin)
        self.form_layout.addRow("动作最大尝试", self.action_attempts_spin)
        self.form_layout.addRow("动作重试间隔", self.action_retry_spin)
        if self.before_actions_editor is not None:
            self.form_layout.addRow("每轮检测前动作", self.before_actions_editor)
        if self.after_no_match_actions_editor is not None:
            self.form_layout.addRow("每轮未命中后动作", self.after_no_match_actions_editor)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        for editor in (
            self.mode_combo,
            self.interval_spin,
            self.max_attempts_spin,
            self.timeout_spin,
            self.action_attempts_spin,
            self.action_retry_spin,
        ):
            if isinstance(editor, QComboBox):
                editor.currentIndexChanged.connect(self._mark_changed)
            else:
                editor.valueChanged.connect(self._mark_changed)
        if self.before_actions_editor is not None:
            self.before_actions_editor.changed.connect(self._mark_changed)
        if self.after_no_match_actions_editor is not None:
            self.after_no_match_actions_editor.changed.connect(self._mark_changed)
        self.set_policies(self._condition_policy, self._action_policy)
        self.set_advanced_visible(show_advanced)

    def _mark_changed(self) -> None:
        self._refresh_summary()
        if not self._loading:
            self.changed.emit()

    def set_mode(self, mode: ConditionMode) -> None:
        index = self.mode_combo.findData(mode)
        self.mode_combo.setCurrentIndex(index)

    def mode(self) -> ConditionMode:
        return ConditionMode(self.mode_combo.currentData())

    def set_policies(
        self,
        condition_policy: ConditionPolicy,
        action_policy: ActionPolicy,
    ) -> None:
        self._loading = True
        self._condition_policy = condition_policy
        self._action_policy = action_policy
        self.set_mode(condition_policy.mode)
        self.interval_spin.setValue(condition_policy.interval_seconds)
        self.max_attempts_spin.setValue(condition_policy.max_attempts or 0)
        self.timeout_spin.setValue(condition_policy.timeout_seconds or 0.0)
        self.action_attempts_spin.setValue(action_policy.max_attempts)
        self.action_retry_spin.setValue(action_policy.retry_interval_seconds)
        if self.before_actions_editor is not None:
            self.before_actions_editor.set_actions(condition_policy.before_attempt_actions)
        if self.after_no_match_actions_editor is not None:
            self.after_no_match_actions_editor.set_actions(condition_policy.after_no_match_actions)
        self._loading = False
        self._refresh_summary()

    def commit_pending(self) -> None:
        if self.before_actions_editor is not None:
            self.before_actions_editor.commit_pending()
        if self.after_no_match_actions_editor is not None:
            self.after_no_match_actions_editor.commit_pending()

    def set_advanced_visible(self, visible: bool) -> None:
        self._show_advanced = visible
        for editor in (self.timeout_spin, self.action_retry_spin):
            self._set_row_visible(editor, visible)
        if self.before_actions_editor is not None:
            self._set_row_visible(self.before_actions_editor, visible)
            self.before_actions_editor.set_advanced_visible(visible)
        if self.after_no_match_actions_editor is not None:
            self._set_row_visible(self.after_no_match_actions_editor, visible)
            self.after_no_match_actions_editor.set_advanced_visible(visible)

    def _set_row_visible(self, editor: QWidget, visible: bool) -> None:
        editor.setVisible(visible)
        label = self.form_layout.labelForField(editor)
        if label is not None:
            label.setVisible(visible)

    def _refresh_summary(self) -> None:
        if self.mode() is ConditionMode.ONCE:
            condition_summary = "单次检测"
        else:
            condition_summary = f"持续检测：每 {self.interval_spin.value():g} 秒一次"
            attempts = self.max_attempts_spin.value()
            if attempts:
                condition_summary += f"，最多 {attempts} 次"
            elif self.timeout_spin.value():
                condition_summary += f"，最长 {self.timeout_spin.value():g} 秒"
        attempts = self.action_attempts_spin.value()
        if attempts <= 1:
            action_summary = "动作失败：不重试"
        else:
            action_summary = f"动作失败：最多尝试 {attempts} 次"
            if self.action_retry_spin.value():
                action_summary += f"，每 {self.action_retry_spin.value():g} 秒重试"
        self.summary_label.setText(f"{condition_summary}\n{action_summary}")

    def policies(self) -> tuple[ConditionPolicy, ActionPolicy]:
        self.commit_pending()
        mode = self.mode()
        max_attempts = 1 if mode is ConditionMode.ONCE else self.max_attempts_spin.value() or None
        condition = ConditionPolicy(
            mode=mode,
            interval_seconds=self.interval_spin.value(),
            max_attempts=max_attempts,
            timeout_seconds=self.timeout_spin.value() or None,
            before_attempt_actions=(
                self.before_actions_editor.action_specs()
                if self.before_actions_editor is not None
                else self._condition_policy.before_attempt_actions
            ),
            after_no_match_actions=(
                self.after_no_match_actions_editor.action_specs()
                if self.after_no_match_actions_editor is not None
                else self._condition_policy.after_no_match_actions
            ),
        )
        action = ActionPolicy(
            max_attempts=self.action_attempts_spin.value(),
            retry_interval_seconds=self.action_retry_spin.value(),
        )
        return condition, action

    def _mode_changed(self) -> None:
        once = self.mode() is ConditionMode.ONCE
        if once:
            self.max_attempts_spin.setValue(1)
        self.max_attempts_spin.setEnabled(not once)
        self.timeout_spin.setEnabled(not once)

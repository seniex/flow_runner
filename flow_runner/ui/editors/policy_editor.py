from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QFormLayout, QSpinBox, QWidget

from flow_runner.capabilities.registry import CapabilityRegistry
from flow_runner.domain.enums import ConditionMode
from flow_runner.domain.policies import ActionPolicy, ConditionPolicy
from flow_runner.ui.editors.action_editor import ActionEditor


class PolicyEditor(QWidget):
    def __init__(self, registry: CapabilityRegistry | None = None) -> None:
        super().__init__()
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("检查一次", ConditionMode.ONCE)
        self.mode_combo.addItem("等待满足", ConditionMode.UNTIL)
        self.interval_spin = QDoubleSpinBox()
        self.interval_spin.setRange(0.0, 1_000_000.0)
        self.interval_spin.setDecimals(3)
        self.max_attempts_spin = QSpinBox()
        self.max_attempts_spin.setRange(0, 1_000_000)
        self.max_attempts_spin.setSpecialValueText("无限")
        self.timeout_spin = QDoubleSpinBox()
        self.timeout_spin.setRange(0.0, 1_000_000.0)
        self.timeout_spin.setDecimals(3)
        self.timeout_spin.setSpecialValueText("无")
        self.action_attempts_spin = QSpinBox()
        self.action_attempts_spin.setRange(1, 1_000_000)
        self.action_retry_spin = QDoubleSpinBox()
        self.action_retry_spin.setRange(0.0, 1_000_000.0)
        self.action_retry_spin.setDecimals(3)
        self._condition_policy = ConditionPolicy()
        self._action_policy = ActionPolicy()
        self.before_actions_editor = ActionEditor(registry) if registry is not None else None
        self.after_no_match_actions_editor = (
            ActionEditor(registry) if registry is not None else None
        )
        layout = QFormLayout(self)
        layout.addRow("检测模式", self.mode_combo)
        layout.addRow("轮询间隔（秒）", self.interval_spin)
        layout.addRow("最大检测次数", self.max_attempts_spin)
        layout.addRow("检测超时（秒）", self.timeout_spin)
        layout.addRow("动作最大尝试", self.action_attempts_spin)
        layout.addRow("动作重试间隔", self.action_retry_spin)
        if self.before_actions_editor is not None:
            layout.addRow("每轮检测前动作", self.before_actions_editor)
        if self.after_no_match_actions_editor is not None:
            layout.addRow("每轮未命中后动作", self.after_no_match_actions_editor)
        self.mode_combo.currentIndexChanged.connect(self._mode_changed)
        self.set_policies(self._condition_policy, self._action_policy)

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

    def policies(self) -> tuple[ConditionPolicy, ActionPolicy]:
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

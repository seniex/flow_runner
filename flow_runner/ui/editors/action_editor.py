from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from flow_runner.capabilities.registry import CapabilityRegistry
from flow_runner.domain.actions import ActionSpec
from flow_runner.ui.editors.model_form import ModelForm


class ActionEditor(QWidget):
    def __init__(self, registry: CapabilityRegistry) -> None:
        super().__init__()
        self.registry = registry
        self.capability_combo = QComboBox()
        for metadata in registry.action_metadata():
            self.capability_combo.addItem(metadata.name, metadata.name)
        self._actions: list[ActionSpec] = []
        self.config_container = QWidget()
        self.config_layout = QVBoxLayout(self.config_container)
        self.config_form: ModelForm | None = None
        self.action_list = QListWidget()
        self.add_button = QPushButton("添加动作")
        self.update_button = QPushButton("更新动作")
        self.remove_button = QPushButton("删除动作")
        self.up_button = QPushButton("上移")
        self.down_button = QPushButton("下移")
        self.error_label = QLabel("")
        layout = QVBoxLayout(self)
        layout.addWidget(self.capability_combo)
        layout.addWidget(self.config_container)
        layout.addWidget(self.action_list)
        buttons = QHBoxLayout()
        for button in (
            self.add_button,
            self.update_button,
            self.remove_button,
            self.up_button,
            self.down_button,
        ):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        layout.addWidget(self.error_label)
        self.capability_combo.currentIndexChanged.connect(self._rebuild_form)
        self.action_list.currentRowChanged.connect(self._load_current)
        self.add_button.clicked.connect(self._add_current)
        self.update_button.clicked.connect(self._update_current)
        self.remove_button.clicked.connect(self._remove_current)
        self.up_button.clicked.connect(lambda: self._move_current(-1))
        self.down_button.clicked.connect(lambda: self._move_current(1))
        self._rebuild_form()

    def set_actions(self, actions: list[ActionSpec]) -> None:
        self._actions = list(actions)
        self._refresh_list()
        if self._actions:
            self.action_list.setCurrentRow(0)

    def action_specs(self) -> list[ActionSpec]:
        return list(self._actions)

    def _rebuild_form(self) -> None:
        while self.config_layout.count():
            item = self.config_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.config_form = None
        capability = self.capability_combo.currentData()
        if not isinstance(capability, str):
            return
        self.config_form = ModelForm(self.registry.action(capability).config_model)
        self.config_layout.addWidget(self.config_form)

    def _add_current(self) -> None:
        action = self._current_action()
        if action is None:
            return
        self._actions.append(action)
        self._refresh_list()
        self.action_list.setCurrentRow(len(self._actions) - 1)

    def _update_current(self) -> None:
        row = self.action_list.currentRow()
        if not 0 <= row < len(self._actions):
            self.error_label.setText("请先选择要更新的动作")
            return
        action = self._current_action()
        if action is None:
            return
        self._actions[row] = action
        self._refresh_list()
        self.action_list.setCurrentRow(row)

    def _current_action(self) -> ActionSpec | None:
        capability = self.capability_combo.currentData()
        if not isinstance(capability, str) or self.config_form is None:
            return None
        try:
            config = self.registry.validated_action_config(
                capability,
                self.config_form.values(),
            )
        except ValueError as error:
            self.error_label.setText(str(error))
            return None
        self.error_label.clear()
        return ActionSpec(capability=capability, config=config)

    def _load_current(self, row: int) -> None:
        if not 0 <= row < len(self._actions):
            return
        action = self._actions[row]
        index = self.capability_combo.findData(action.capability)
        if index < 0:
            self.error_label.setText(f"未知动作能力：{action.capability}")
            return
        self.capability_combo.blockSignals(True)
        self.capability_combo.setCurrentIndex(index)
        self.capability_combo.blockSignals(False)
        self._rebuild_form()
        if self.config_form is not None:
            self.config_form.set_values(action.config)
        self.error_label.clear()

    def _remove_current(self) -> None:
        row = self.action_list.currentRow()
        if 0 <= row < len(self._actions):
            self._actions.pop(row)
            self._refresh_list()

    def _move_current(self, direction: int) -> None:
        row = self.action_list.currentRow()
        destination = row + direction
        if not 0 <= row < len(self._actions) or not 0 <= destination < len(self._actions):
            return
        self._actions[row], self._actions[destination] = (
            self._actions[destination],
            self._actions[row],
        )
        self._refresh_list()
        self.action_list.setCurrentRow(destination)

    def _refresh_list(self) -> None:
        self.action_list.clear()
        self.action_list.addItems([action.capability for action in self._actions])

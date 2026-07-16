from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from flow_runner.capabilities.registry import CapabilityRegistry
from flow_runner.domain.actions import ActionSpec
from flow_runner.ui.editor_metadata import common_fields_for
from flow_runner.ui.editors.model_form import ModelForm
from flow_runner.ui.layouts import CompactFlowLayout
from flow_runner.ui.localization import action_summary, capability_label
from flow_runner.ui.region_capture import PointCapture
from flow_runner.ui.result_bindings import ResultBindingOption


class ActionEditor(QWidget):
    changed = Signal()

    def __init__(
        self,
        registry: CapabilityRegistry,
        *,
        show_advanced: bool = False,
        pick_point: Callable[[str], PointCapture | None] | None = None,
    ) -> None:
        super().__init__()
        self.registry = registry
        self._show_advanced = show_advanced
        self._pick_point = pick_point
        self._binding_options: tuple[ResultBindingOption, ...] = ()
        self._loading = False
        self._current_pending = False
        self.capability_container = QWidget()
        self.capability_container.setObjectName("actionCapabilitySelector")
        self.capability_layout = CompactFlowLayout(self.capability_container, spacing=6)
        self.capability_buttons = QButtonGroup(self)
        self.capability_buttons.setExclusive(True)
        for metadata in registry.action_metadata():
            button = QPushButton(capability_label(metadata.name))
            button.setObjectName("actionCapabilityButton")
            button.setCheckable(True)
            button.setProperty("capability", metadata.name)
            self.capability_buttons.addButton(button)
            self.capability_layout.addWidget(button)
        if self.capability_buttons.buttons():
            self.capability_buttons.buttons()[0].setChecked(True)
        self._actions: list[ActionSpec] = []
        self.config_container = QWidget()
        self.config_layout = QVBoxLayout(self.config_container)
        self.config_form: ModelForm | None = None
        self.action_list = QListWidget()
        self.add_button = QPushButton("添加动作")
        self.update_button = QPushButton("更新动作")
        self.remove_button = QPushButton("删除动作")
        self.copy_button = QPushButton("复制动作")
        self.up_button = QPushButton("上移")
        self.down_button = QPushButton("下移")
        self.error_label = QLabel("")
        layout = QVBoxLayout(self)
        layout.addWidget(self.capability_container)
        layout.addWidget(self.config_container)
        layout.addWidget(self.action_list)
        buttons = QHBoxLayout()
        for button in (
            self.add_button,
            self.update_button,
            self.remove_button,
            self.copy_button,
            self.up_button,
            self.down_button,
        ):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        layout.addWidget(self.error_label)
        self.capability_buttons.buttonClicked.connect(self._capability_changed)
        self.action_list.currentItemChanged.connect(self._selection_changed)
        self.add_button.clicked.connect(self._add_current)
        self.update_button.clicked.connect(self._update_current)
        self.remove_button.clicked.connect(self._remove_current)
        self.copy_button.clicked.connect(self._copy_current)
        self.up_button.clicked.connect(lambda: self._move_current(-1))
        self.down_button.clicked.connect(lambda: self._move_current(1))
        self._rebuild_form()

    def set_binding_options(self, options: tuple[ResultBindingOption, ...]) -> None:
        self._binding_options = options
        if self.config_form is not None:
            self.config_form.set_binding_options(options)

    def set_actions(self, actions: list[ActionSpec]) -> None:
        self._loading = True
        self._current_pending = False
        self._actions = list(actions)
        self._refresh_list()
        if self._actions:
            self.action_list.setCurrentRow(0)
        self._loading = False
        if self._actions:
            self._load_current(0)

    def action_specs(self) -> list[ActionSpec]:
        return list(self._actions)

    def commit_current(self) -> None:
        row = self.action_list.currentRow()
        if not 0 <= row < len(self._actions):
            return
        self._commit_row(row)

    def _commit_row(self, row: int) -> None:
        action = self._build_current_action()
        self._actions[row] = action
        self._current_pending = False
        item = self.action_list.item(row)
        if item is not None:
            item.setText(f"{row + 1}. {self._action_summary(action)}")

    def _action_summary(self, action: ActionSpec) -> str:
        labels = {option.expression: option.label for option in self._binding_options}
        return action_summary(action, binding_labels=labels)

    def commit_pending(self) -> None:
        if not self._current_pending:
            return
        if not 0 <= self.action_list.currentRow() < len(self._actions):
            raise ValueError("请先添加当前动作")
        self.commit_current()

    def _capability_changed(self, _button: object = None) -> None:
        self._rebuild_form()
        if not self._loading:
            self._current_pending = True
            self.changed.emit()

    def _rebuild_form(self) -> None:
        while self.config_layout.count():
            item = self.config_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.config_form = None
        capability = self.current_capability()
        if capability is None:
            return
        self.config_form = ModelForm(
            self.registry.action(capability).config_model,
            common_fields=common_fields_for(capability),
            show_advanced=self._show_advanced,
            pick_point=self._pick_point,
        )
        self.config_form.set_binding_options(self._binding_options)
        self.config_form.changed.connect(self._form_changed)
        self.config_layout.addWidget(self.config_form)

    def set_advanced_visible(self, visible: bool) -> None:
        self._show_advanced = visible
        if self.config_form is not None:
            self.config_form.set_advanced_visible(visible)

    def _form_changed(self) -> None:
        if not self._loading:
            self._current_pending = True
            self.changed.emit()

    def _add_current(self) -> None:
        action = self._current_action()
        if action is None:
            return
        self._actions.append(action)
        self._current_pending = False
        self._refresh_and_select(len(self._actions) - 1)
        self.changed.emit()

    def _update_current(self) -> None:
        row = self.action_list.currentRow()
        if not 0 <= row < len(self._actions):
            self.error_label.setText("请先选择要更新的动作")
            return
        action = self._current_action()
        if action is None:
            return
        self._actions[row] = action
        self._current_pending = False
        item = self.action_list.item(row)
        if item is not None:
            item.setText(f"{row + 1}. {self._action_summary(action)}")
        self.changed.emit()

    def _current_action(self) -> ActionSpec | None:
        try:
            action = self._build_current_action()
        except ValueError as error:
            self.error_label.setText(str(error))
            return None
        self.error_label.clear()
        return action

    def _build_current_action(self) -> ActionSpec:
        capability = self.current_capability()
        if capability is None or self.config_form is None:
            raise ValueError("请选择动作类型")
        config = self.registry.validated_action_config(
            capability,
            self.config_form.values(),
        )
        return ActionSpec(capability=capability, config=config)

    def _selection_changed(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        if self._loading:
            return
        previous_row = self.action_list.row(previous) if previous is not None else -1
        if (
            self._current_pending
            and previous is not None
            and 0 <= previous_row < len(self._actions)
        ):
            try:
                self._commit_row(previous_row)
            except ValueError as error:
                self.error_label.setText(str(error))
                self._loading = True
                self.action_list.setCurrentItem(previous)
                self._loading = False
                return
        self._load_current(self.action_list.row(current) if current is not None else -1)

    def _load_current(self, row: int) -> None:
        if not 0 <= row < len(self._actions):
            return
        action = self._actions[row]
        button = self._button_for_capability(action.capability)
        if button is None:
            self.error_label.setText(f"未知动作能力：{action.capability}")
            return
        self._loading = True
        self.capability_buttons.blockSignals(True)
        button.setChecked(True)
        self.capability_buttons.blockSignals(False)
        self._rebuild_form()
        if self.config_form is not None:
            self.config_form.set_values(action.config)
        self._current_pending = False
        self._loading = False
        self.error_label.clear()

    def current_capability(self) -> str | None:
        button = self.capability_buttons.checkedButton()
        capability = button.property("capability") if button is not None else None
        return capability if isinstance(capability, str) else None

    def _button_for_capability(self, capability: str) -> QPushButton | None:
        for button in self.capability_buttons.buttons():
            if isinstance(button, QPushButton) and button.property("capability") == capability:
                return button
        return None

    def _remove_current(self) -> None:
        row = self.action_list.currentRow()
        if 0 <= row < len(self._actions):
            self._actions.pop(row)
            self._current_pending = False
            self._refresh_and_select(min(row, len(self._actions) - 1))
            self.changed.emit()

    def _copy_current(self) -> None:
        row = self.action_list.currentRow()
        if not 0 <= row < len(self._actions):
            self.error_label.setText("请先选择要复制的动作")
            return
        try:
            self.commit_pending()
        except ValueError as error:
            self.error_label.setText(str(error))
            return
        self._actions.insert(row + 1, self._actions[row].model_copy(deep=True))
        self._current_pending = False
        self._refresh_and_select(row + 1)
        self.changed.emit()

    def _move_current(self, direction: int) -> None:
        row = self.action_list.currentRow()
        destination = row + direction
        if not 0 <= row < len(self._actions) or not 0 <= destination < len(self._actions):
            return
        try:
            self.commit_pending()
        except ValueError as error:
            self.error_label.setText(str(error))
            return
        self._actions[row], self._actions[destination] = (
            self._actions[destination],
            self._actions[row],
        )
        self._current_pending = False
        self._refresh_and_select(destination)
        self.changed.emit()

    def _refresh_and_select(self, row: int) -> None:
        self._loading = True
        self._refresh_list()
        if row >= 0:
            self.action_list.setCurrentRow(row)
        self._loading = False
        self._load_current(row)

    def _refresh_list(self) -> None:
        self.action_list.clear()
        self.action_list.addItems(
            [
                f"{index}. {self._action_summary(action)}"
                for index, action in enumerate(self._actions, 1)
            ]
        )

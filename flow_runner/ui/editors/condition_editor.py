from collections.abc import Callable
from typing import Any, Literal, cast

from pydantic import BaseModel
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from flow_runner.capabilities.registry import CapabilityRegistry
from flow_runner.domain.conditions import ConditionGroup, ConditionNode, LeafCondition
from flow_runner.domain.errors import ConfigurationError
from flow_runner.domain.project import AutomationStep
from flow_runner.ui.editor_metadata import common_fields_for
from flow_runner.ui.editors.model_form import ModelForm
from flow_runner.ui.layouts import CompactFlowLayout
from flow_runner.ui.localization import capability_label, choice_label, field_label
from flow_runner.ui.region_capture import RegionCaptureService
from flow_runner.ui.widgets import FocusWheelComboBox

ConditionOperator = Literal["and", "or", "not"]


class ConditionEditor(QWidget):
    changed = Signal()

    def __init__(
        self,
        registry: CapabilityRegistry,
        *,
        confirm_discard: Callable[[tuple[str, ...]], bool] | None = None,
        show_advanced: bool = False,
        region_capture: RegionCaptureService | None = None,
    ) -> None:
        super().__init__()
        self.registry = registry
        self._show_advanced = show_advanced
        self._region_capture = region_capture
        self.confirm_discard = confirm_discard or self._confirm_discard
        self._root: ConditionNode | None = None
        self._selected_path: tuple[int, ...] | None = None
        self._loading = False
        self._active_capability: str | None = None
        self.enabled_check = QCheckBox("使用条件")
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.node_id_edit = QLineEdit()
        self.operator_combo = FocusWheelComboBox()
        for operator in ("and", "or", "not"):
            self.operator_combo.addItem(choice_label(operator), operator)
        self.capability_combo = FocusWheelComboBox()
        for metadata in registry.condition_metadata():
            self.capability_combo.addItem(capability_label(metadata.name), metadata.name)
        self.form_container = QWidget()
        self.form_layout = QVBoxLayout(self.form_container)
        self.config_form: ModelForm | None = None
        self.message_label = QLabel("")
        self.add_leaf_button = QPushButton("添加叶子")
        self.add_and_button = QPushButton("添加并且条件")
        self.add_or_button = QPushButton("添加或者条件")
        self.add_not_button = QPushButton("添加取反条件")
        self.remove_button = QPushButton("删除节点")
        layout = QVBoxLayout(self)
        layout.addWidget(self.enabled_check)
        layout.addWidget(self.tree)
        buttons = QHBoxLayout()
        for button in (
            self.add_leaf_button,
            self.add_and_button,
            self.add_or_button,
            self.add_not_button,
            self.remove_button,
        ):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        controls = QWidget()
        controls.setObjectName("conditionCompactControls")
        self.control_layout = CompactFlowLayout(controls)
        self.control_layout.addField("节点名称", self.node_id_edit, "node_id")
        self.control_layout.addField("组合方式", self.operator_combo, "operator")
        self.control_layout.addField("检测能力", self.capability_combo, "capability")
        layout.addWidget(controls)
        layout.addWidget(self.form_container)
        layout.addWidget(self.message_label)
        self.capability_combo.currentIndexChanged.connect(self._capability_changed)
        self.enabled_check.toggled.connect(self._update_enabled)
        self.tree.currentItemChanged.connect(self._selection_changed)
        self.add_leaf_button.clicked.connect(self._add_leaf)
        self.add_and_button.clicked.connect(lambda: self._add_group("and"))
        self.add_or_button.clicked.connect(lambda: self._add_group("or"))
        self.add_not_button.clicked.connect(lambda: self._add_group("not"))
        self.remove_button.clicked.connect(self._remove_selected)
        self.enabled_check.toggled.connect(self._mark_changed)
        self.node_id_edit.textChanged.connect(self._mark_changed)
        self.operator_combo.currentIndexChanged.connect(self._mark_changed)
        for button in (
            self.add_leaf_button,
            self.add_and_button,
            self.add_or_button,
            self.add_not_button,
            self.remove_button,
        ):
            button.clicked.connect(self._mark_changed)
        self._switch_form()
        self._update_enabled(False)

    def set_condition(self, condition: ConditionNode | None) -> None:
        self._loading = True
        self._root = condition
        self._selected_path = None
        if condition is None:
            self.enabled_check.setChecked(False)
            self.message_label.clear()
            self._rebuild_tree()
            self._loading = False
            return
        self.enabled_check.setChecked(True)
        self.message_label.clear()
        self._rebuild_tree()
        self._loading = False

    def _mark_changed(self) -> None:
        if not self._loading:
            self.changed.emit()

    def condition(self) -> ConditionNode | None:
        if not self.enabled_check.isChecked():
            return None
        self._commit_selected()
        if self._root is None:
            raise ValueError("请添加条件节点")
        self._root = self._validate_node(self._root)
        return self._root

    def condition_for_bindings(self) -> ConditionNode | None:
        if not self.enabled_check.isChecked():
            return None
        previous = self._root
        try:
            self._commit_selected()
            if self._root is not None:
                self._root = self._validate_node(self._root)
        except ValueError:
            self._root = previous
        return self._root

    def _selection_changed(
        self,
        current: QTreeWidgetItem | None,
        previous: QTreeWidgetItem | None,
    ) -> None:
        if self._loading:
            return
        try:
            self._commit_selected()
        except ValueError as error:
            self.message_label.setText(str(error))
            if previous is not None:
                self._loading = True
                self.tree.setCurrentItem(previous)
                self._loading = False
            return
        self.message_label.clear()
        self._selected_path = self._item_path(current)
        self._load_selected()

    def _load_selected(self) -> None:
        node = self._selected_node()
        enabled = self.enabled_check.isChecked() and node is not None
        self.node_id_edit.setEnabled(enabled)
        if node is None:
            self.node_id_edit.clear()
            self.operator_combo.setEnabled(False)
            self.capability_combo.setEnabled(False)
            self.form_container.setEnabled(False)
            return
        self.node_id_edit.setText(node.id)
        if isinstance(node, ConditionGroup):
            self.operator_combo.setEnabled(True)
            self.operator_combo.setVisible(True)
            self.capability_combo.setEnabled(False)
            self.capability_combo.setVisible(False)
            self.form_container.setEnabled(False)
            self.form_container.setVisible(False)
            self.operator_combo.setCurrentIndex(self.operator_combo.findData(node.operator))
            return
        self.operator_combo.setEnabled(False)
        self.operator_combo.setVisible(False)
        self.capability_combo.setEnabled(True)
        self.capability_combo.setVisible(True)
        self.form_container.setEnabled(True)
        self.form_container.setVisible(True)
        self._loading = True
        index = self.capability_combo.findData(node.capability)
        if index >= 0:
            self.capability_combo.setCurrentIndex(index)
        self._loading = False
        self._switch_form(node.config)

    def _commit_selected(self) -> None:
        path = self._selected_path
        node = self._selected_node()
        if path is None or node is None:
            return
        node_id = self.node_id_edit.text().strip()
        if not node_id:
            raise ValueError("节点名称不能为空")
        if isinstance(node, ConditionGroup):
            operator = self.operator_combo.currentData()
            if operator not in {"and", "or", "not"}:
                raise ValueError("请选择组合方式")
            replacement: ConditionNode = ConditionGroup(
                id=node_id,
                operator=cast(ConditionOperator, operator),
                children=node.children,
            )
        else:
            capability = self.capability_combo.currentData()
            if not isinstance(capability, str) or self.config_form is None:
                raise ValueError("请选择检测能力")
            config = (
                self.registry.condition(capability)
                .config_model.model_validate(self.config_form.values())
                .model_dump(mode="python")
            )
            replacement = LeafCondition(id=node_id, capability=capability, config=config)
        self._root = self._replace_node(self._root, path, replacement)
        item = self.tree.currentItem()
        if item is not None:
            item.setText(0, self._node_label(replacement))

    def _add_leaf(self) -> None:
        if not self.enabled_check.isChecked():
            self.enabled_check.setChecked(True)
        try:
            self._commit_selected()
            template = self._first_leaf(self._selected_node() or self._root)
            leaf = self._new_leaf(template)
            self._insert_node(leaf)
        except ValueError as error:
            self.message_label.setText(str(error))

    def _add_group(self, operator: ConditionOperator) -> None:
        if not self.enabled_check.isChecked():
            self.enabled_check.setChecked(True)
        try:
            self._commit_selected()
            selected = self._selected_node()
            if selected is None:
                leaf = self._new_leaf(None)
                group = ConditionGroup(
                    id=self._unique_id("group"),
                    operator=operator,
                    children=[leaf],
                )
                self._root = group
            elif operator == "not":
                group = ConditionGroup(
                    id=self._unique_id("not"),
                    operator="not",
                    children=[selected],
                )
                self._root = self._replace_node(self._root, self._selected_path or (), group)
            else:
                sibling = self._new_leaf(self._first_leaf(selected))
                group = ConditionGroup(
                    id=self._unique_id(operator),
                    operator=operator,
                    children=[selected, sibling],
                )
                self._root = self._replace_node(self._root, self._selected_path or (), group)
            self.message_label.clear()
            self._rebuild_tree()
        except ValueError as error:
            self.message_label.setText(str(error))

    def _insert_node(self, node: ConditionNode) -> None:
        selected = self._selected_node()
        path = self._selected_path
        if self._root is None or selected is None or path is None:
            self._root = node
        elif isinstance(selected, ConditionGroup):
            if selected.operator == "not":
                raise ValueError("NOT 组只能包含一个子条件")
            replacement = ConditionGroup(
                id=selected.id,
                operator=selected.operator,
                children=[*selected.children, node],
            )
            self._root = self._replace_node(self._root, path, replacement)
        elif not path:
            self._root = ConditionGroup(
                id=self._unique_id("and"),
                operator="and",
                children=[selected, node],
            )
        else:
            parent_path = path[:-1]
            parent = self._node_at(self._root, parent_path)
            if not isinstance(parent, ConditionGroup) or parent.operator == "not":
                raise ValueError("当前节点不能添加同级条件")
            replacement = ConditionGroup(
                id=parent.id,
                operator=parent.operator,
                children=[*parent.children, node],
            )
            self._root = self._replace_node(self._root, parent_path, replacement)
        self.message_label.clear()
        self._rebuild_tree()

    def _remove_selected(self) -> None:
        path = self._selected_path
        if path is None or self._root is None:
            return
        if not path:
            self._root = None
        else:
            parent_path = path[:-1]
            parent = self._node_at(self._root, parent_path)
            if not isinstance(parent, ConditionGroup):
                return
            children = [child for index, child in enumerate(parent.children) if index != path[-1]]
            if not children:
                self.message_label.setText("组合条件至少保留一个子节点")
                return
            replacement: ConditionNode = (
                children[0]
                if len(children) == 1 and parent.operator != "not"
                else ConditionGroup(
                    id=parent.id,
                    operator=parent.operator,
                    children=children,
                )
            )
            self._root = self._replace_node(self._root, parent_path, replacement)
        self._rebuild_tree()

    def _rebuild_tree(self) -> None:
        self._loading = True
        self.tree.clear()
        if self._root is not None:
            root_item = self._build_item(self._root, ())
            self.tree.addTopLevelItem(root_item)
            root_item.setExpanded(True)
            self.tree.setCurrentItem(root_item)
            self._selected_path = ()
        else:
            self._selected_path = None
        self._loading = False
        self._load_selected()

    def _build_item(self, node: ConditionNode, path: tuple[int, ...]) -> QTreeWidgetItem:
        item = QTreeWidgetItem([self._node_label(node)])
        item.setData(0, Qt.ItemDataRole.UserRole, path)
        if isinstance(node, ConditionGroup):
            for index, child in enumerate(node.children):
                item.addChild(self._build_item(child, (*path, index)))
            item.setExpanded(True)
        return item

    @staticmethod
    def _node_label(node: ConditionNode) -> str:
        if isinstance(node, ConditionGroup):
            return f"{node.id} [{choice_label(node.operator)}]"
        return f"{node.id} [{capability_label(node.capability)}]"

    @staticmethod
    def _item_path(item: QTreeWidgetItem | None) -> tuple[int, ...] | None:
        if item is None:
            return None
        path = item.data(0, Qt.ItemDataRole.UserRole)
        return tuple(path) if isinstance(path, (list, tuple)) else None

    def _selected_node(self) -> ConditionNode | None:
        if self._root is None or self._selected_path is None:
            return None
        return self._node_at(self._root, self._selected_path)

    @classmethod
    def _node_at(cls, node: ConditionNode, path: tuple[int, ...]) -> ConditionNode:
        current = node
        for index in path:
            if not isinstance(current, ConditionGroup):
                raise ValueError("条件树路径无效")
            current = current.children[index]
        return current

    @classmethod
    def _replace_node(
        cls,
        root: ConditionNode | None,
        path: tuple[int, ...],
        replacement: ConditionNode,
    ) -> ConditionNode:
        if root is None or not path:
            return replacement
        if not isinstance(root, ConditionGroup):
            raise ValueError("条件树路径无效")
        index = path[0]
        children = list(root.children)
        children[index] = cls._replace_node(children[index], path[1:], replacement)
        return ConditionGroup(id=root.id, operator=root.operator, children=children)

    def _new_leaf(self, template: LeafCondition | None) -> LeafCondition:
        if template is not None:
            return LeafCondition(
                id=self._unique_id("condition"),
                capability=template.capability,
                config=template.config,
            )
        capability = self._default_capability()
        return LeafCondition(
            id=self._unique_id("condition"),
            capability=capability,
            config={},
        )

    def _validate_node(self, node: ConditionNode) -> ConditionNode:
        if isinstance(node, ConditionGroup):
            return ConditionGroup(
                id=node.id,
                operator=node.operator,
                children=[self._validate_node(child) for child in node.children],
            )
        try:
            config = (
                self.registry.condition(node.capability)
                .config_model.model_validate(node.config)
                .model_dump(mode="python")
            )
        except (ValueError, ConfigurationError) as error:
            raise ValueError(f"条件节点 '{node.id}' 配置无效：{error}") from error
        return LeafCondition(id=node.id, capability=node.capability, config=config)

    def _default_capability(self) -> str:
        preferred = self.capability_combo.findData("vision.ocr")
        index = preferred if preferred >= 0 else 0
        capability = self.capability_combo.itemData(index)
        if not isinstance(capability, str):
            raise ValueError("没有可用的检测能力")
        return capability

    @classmethod
    def _first_leaf(cls, node: ConditionNode | None) -> LeafCondition | None:
        if isinstance(node, LeafCondition):
            return node
        if isinstance(node, ConditionGroup):
            for child in node.children:
                leaf = cls._first_leaf(child)
                if leaf is not None:
                    return leaf
        return None

    def _unique_id(self, prefix: str) -> str:
        used = self._all_ids(self._root)
        index = 1
        while f"{prefix}_{index}" in used:
            index += 1
        return f"{prefix}_{index}"

    @classmethod
    def _all_ids(cls, node: ConditionNode | None) -> set[str]:
        if node is None:
            return set()
        result = {node.id}
        if isinstance(node, ConditionGroup):
            for child in node.children:
                result.update(cls._all_ids(child))
        return result

    def _capability_changed(self, _index: int) -> None:
        if self._loading:
            return
        capability = self.capability_combo.currentData()
        if not isinstance(capability, str) or capability == self._active_capability:
            return
        previous: dict[str, Any] = {}
        if self.config_form is not None:
            try:
                previous = self.config_form.values()
            except ValueError as error:
                self.message_label.setText(str(error))
                self._restore_active_capability()
                return
        allowed = set(self.registry.condition(capability).config_model.model_fields)
        discarded = tuple(name for name in previous if name not in allowed)
        if discarded and not self.confirm_discard(discarded):
            self._restore_active_capability()
            return
        self._switch_form(previous)
        self._mark_changed()
        self.message_label.setText(
            f"已舍弃检测能力专属字段：{'、'.join(field_label(name) for name in discarded)}"
            if discarded
            else ""
        )

    def _restore_active_capability(self) -> None:
        if self._active_capability is None:
            return
        self._loading = True
        self.capability_combo.setCurrentIndex(
            self.capability_combo.findData(self._active_capability)
        )
        self._loading = False

    def _switch_form(self, values: dict[str, Any] | None = None) -> None:
        previous = values
        if previous is None and self.config_form is not None:
            try:
                previous = self.config_form.values()
            except ValueError:
                previous = {}
        while self.form_layout.count():
            item = self.form_layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        capability = self.capability_combo.currentData()
        self.config_form = None
        if not isinstance(capability, str):
            return
        model_type = self.registry.condition(capability).config_model
        self.config_form = ModelForm(
            model_type,
            common_fields=common_fields_for(capability),
            show_advanced=self._show_advanced,
            pick_region=(
                lambda target: (
                    self._region_capture.pick_region(target, self)
                    if self._region_capture is not None
                    else None
                )
            ),
            capture_template=(
                lambda target: (
                    self._region_capture.capture_template(target, self)
                    if self._region_capture is not None
                    else None
                )
            ),
        )
        self.config_form.changed.connect(self._mark_changed)
        if previous:
            allowed = set(model_type.model_fields)
            self.config_form.set_values(
                {name: value for name, value in previous.items() if name in allowed}
            )
        self.form_layout.addWidget(self.config_form)
        self._active_capability = capability

    def set_advanced_visible(self, visible: bool) -> None:
        self._show_advanced = visible
        if self.config_form is not None:
            self.config_form.set_advanced_visible(visible)

    def _confirm_discard(self, fields: tuple[str, ...]) -> bool:
        field_list = "、".join(field_label(name) for name in fields)
        return (
            QMessageBox.question(
                self,
                "确认切换检测能力",
                f"切换后将舍弃以下专属字段：{field_list}\n是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            is QMessageBox.StandardButton.Yes
        )

    def _update_enabled(self, enabled: bool) -> None:
        self.tree.setEnabled(enabled)
        for button in (
            self.add_leaf_button,
            self.add_and_button,
            self.add_or_button,
            self.add_not_button,
            self.remove_button,
        ):
            button.setEnabled(enabled)
        self._load_selected()


def switch_condition_capability(
    step: AutomationStep,
    capability: str,
    config_model: type[BaseModel],
    *,
    required_config: dict[str, Any] | None = None,
) -> tuple[AutomationStep, dict[str, Any]]:
    condition = step.condition
    if not isinstance(condition, LeafCondition):
        raise ValueError("capability switching requires a leaf condition")
    allowed = set(config_model.model_fields)
    preserved = {key: value for key, value in condition.config.items() if key in allowed}
    discarded = {key: value for key, value in condition.config.items() if key not in allowed}
    preserved.update(required_config or {})
    validated = config_model.model_validate(preserved).model_dump(mode="python")
    replacement = LeafCondition(
        id=condition.id,
        capability=capability,
        config=validated,
    )
    return step.model_copy(update={"condition": replacement}), discarded

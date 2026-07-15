import json
from collections.abc import Callable
from enum import Enum
from pathlib import Path
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from flow_runner.capabilities.actions.process import LaunchProcessConfig
from flow_runner.capabilities.actions.window import WindowActionConfig
from flow_runner.ui.launch_file_selection import (
    default_comspec,
    default_python_executable,
    infer_automatic_prefix,
    launch_file_selection,
    replace_automatic_prefix,
)
from flow_runner.ui.layouts import CompactFlowLayout
from flow_runner.ui.localization import choice_label, field_label
from flow_runner.ui.region_capture import Region, TemplateCapture
from flow_runner.ui.result_bindings import ResultBindingOption
from flow_runner.ui.widgets import (
    FocusWheelComboBox,
    FocusWheelDoubleSpinBox,
    FocusWheelSpinBox,
)


class BindingFieldEditor(QWidget):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.combo = FocusWheelComboBox()
        self.custom_edit = QLineEdit()
        self.custom_edit.setPlaceholderText("输入自定义绑定表达式")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.combo)
        layout.addWidget(self.custom_edit)
        self.combo.currentIndexChanged.connect(self._mode_changed)
        self.custom_edit.textChanged.connect(lambda _text: self.changed.emit())
        self.set_options(())

    @property
    def is_custom(self) -> bool:
        return self.combo.currentData() is None

    def set_options(self, options: tuple[ResultBindingOption, ...]) -> None:
        current = self.value() if self.combo.count() else ""
        blocked = self.combo.blockSignals(True)
        self.combo.clear()
        for option in options:
            self.combo.addItem(option.label, option.expression)
        self.combo.addItem("自定义表达式", None)
        self.combo.blockSignals(blocked)
        self.setValue(current)

    def value(self) -> str:
        value = self.combo.currentData()
        return value if isinstance(value, str) else self.custom_edit.text().strip()

    def setValue(self, expression: str) -> None:  # noqa: N802 - Qt-compatible API
        index = self.combo.findData(expression)
        if index >= 0:
            self.combo.setCurrentIndex(index)
        else:
            self.combo.setCurrentIndex(self.combo.count() - 1)
            self.custom_edit.setText(expression)
        self._mode_changed()

    def _mode_changed(self, _index: int = -1) -> None:
        self.custom_edit.setVisible(self.is_custom)
        self.changed.emit()


class TupleFieldEditor(QWidget):
    changed = Signal()

    def __init__(
        self,
        annotation: Any,
        default: Any = None,
        *,
        optional: bool = False,
        allow_pick: bool = False,
    ) -> None:
        super().__init__()
        self.setProperty("fieldKind", "tuple")
        self._optional = optional
        self._arguments = _tuple_arguments(annotation)
        self.mode_combo = FocusWheelComboBox()
        if optional:
            self.mode_combo.addItem("未设置", "none")
        self.mode_combo.addItem("固定值", "fixed")
        self.mode_combo.addItem("动态绑定", "binding")
        self.value_container = QWidget()
        value_layout = QHBoxLayout(self.value_container)
        value_layout.setContentsMargins(0, 0, 0, 0)
        self.value_editors: list[QSpinBox | QDoubleSpinBox] = []
        for argument in self._arguments:
            editor = _create_number_editor(argument)
            editor.setProperty("fieldKind", "tuplePart")
            self.value_editors.append(editor)
            value_layout.addWidget(editor)
        self.binding_selector = BindingFieldEditor()
        self.binding_edit = self.binding_selector.custom_edit
        self.binding_edit.setProperty("fieldKind", "binding")
        self.pages = QStackedWidget()
        if optional:
            self.pages.addWidget(QWidget())
        self.pages.addWidget(self.value_container)
        self.pages.addWidget(self.binding_selector)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.mode_combo)
        layout.addWidget(self.pages, 1)
        self.pick_button = QPushButton("框选区域")
        self.pick_button.setObjectName("pickRegionButton")
        self.pick_button.setVisible(allow_pick)
        layout.addWidget(self.pick_button)
        self.mode_combo.currentIndexChanged.connect(self.pages.setCurrentIndex)
        self.mode_combo.currentIndexChanged.connect(self._emit_changed)
        self.binding_selector.changed.connect(self._emit_changed)
        for editor in self.value_editors:
            editor.valueChanged.connect(self._emit_changed)
        if default is None and optional:
            self.mode_combo.setCurrentIndex(self.mode_combo.findData("none"))
        else:
            self.setValue(default if default is not None else _zero_tuple(self._arguments))

    def _emit_changed(self) -> None:
        self.changed.emit()

    def value(self) -> tuple[int | float, ...] | str | None:
        mode = self.mode_combo.currentData()
        if mode == "none":
            return None
        if mode == "binding":
            return self.binding_selector.value()
        return tuple(editor.value() for editor in self.value_editors)

    def setValue(self, value: Any) -> None:  # noqa: N802 - Qt-compatible API
        if value is None and self._optional:
            self.mode_combo.setCurrentIndex(self.mode_combo.findData("none"))
            return
        if isinstance(value, str) and value.startswith("$"):
            self.setBinding(value)
            return
        if not isinstance(value, (list, tuple)) or len(value) != len(self.value_editors):
            raise ValueError(f"expected a tuple with {len(self.value_editors)} values")
        for editor, item in zip(self.value_editors, value, strict=True):
            editor.setValue(item)
        self.mode_combo.setCurrentIndex(self.mode_combo.findData("fixed"))

    def setBinding(self, expression: str) -> None:  # noqa: N802 - Qt-compatible API
        self.binding_selector.setValue(expression)
        self.mode_combo.setCurrentIndex(self.mode_combo.findData("binding"))


class PathFieldEditor(QWidget):
    changed = Signal()
    fileSelected = Signal(str)

    def __init__(
        self,
        default: Any = None,
        *,
        allow_capture: bool = False,
        file_filter: str = "所有文件 (*)",
    ) -> None:
        super().__init__()
        self.setProperty("fieldKind", "path")
        self._file_filter = file_filter
        self.line_edit = QLineEdit()
        self.browse_button = QPushButton("选择…")
        self.browse_button.setProperty("role", "browse")
        self.capture_button = QPushButton("框选并截图")
        self.capture_button.setObjectName("captureTemplateButton")
        self.capture_button.setVisible(allow_capture)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.line_edit, 1)
        layout.addWidget(self.capture_button)
        layout.addWidget(self.browse_button)
        self.browse_button.clicked.connect(self._browse)
        self.line_edit.textChanged.connect(self._emit_changed)
        if default is not None:
            self.setText(str(default))

    def _emit_changed(self) -> None:
        self.changed.emit()

    def text(self) -> str:
        return self.line_edit.text()

    def setText(self, value: str) -> None:  # noqa: N802 - Qt-compatible API
        self.line_edit.setText(value)

    def clear(self) -> None:
        self.line_edit.clear()

    def _browse(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "选择文件",
            self.text(),
            self._file_filter,
        )
        if path:
            self.setText(path)
            self.fileSelected.emit(path)


class ModelForm(QWidget):
    changed = Signal()

    def __init__(
        self,
        model_type: type[BaseModel],
        *,
        common_fields: frozenset[str] | None = None,
        show_advanced: bool = False,
        pick_region: Callable[[str], Region | None] | None = None,
        capture_template: Callable[[str], TemplateCapture | None] | None = None,
        report_error: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__()
        self.model_type = model_type
        self._common_fields = common_fields
        self._advanced_fields = (
            frozenset(model_type.model_fields) - common_fields
            if common_fields is not None
            else frozenset()
        )
        self._show_advanced = show_advanced
        self._pick_region_callback = pick_region
        self._capture_template_callback = capture_template
        self._report_error = report_error or (
            lambda message: QMessageBox.warning(self, "配置操作失败", message)
        )
        self.editors: dict[str, QWidget] = {}
        self.annotations: dict[str, Any] = {}
        self._binding_options: tuple[ResultBindingOption, ...] = ()
        self._launch_action_form = model_type is LaunchProcessConfig
        self._launch_automatic_arguments: tuple[str, ...] = ()
        self._launch_automatic_working_directory: Path | None = None
        self._window_action_form = model_type is WindowActionConfig
        self.form_layout = CompactFlowLayout(self, wrap=not self._window_action_form)
        for name, field in model_type.model_fields.items():
            annotation, optional = _unwrap_optional(field.annotation)
            default = None if field.is_required() else field.get_default(call_default_factory=True)
            editor = _create_editor(
                name,
                annotation,
                default,
                optional,
                allow_pick=pick_region is not None,
                allow_capture=capture_template is not None,
                file_filter=(
                    "程序和脚本 (*.exe *.com *.py *.pyw *.bat);;所有文件 (*)"
                    if self._launch_action_form and name == "path"
                    else "所有文件 (*)"
                ),
            )
            editor.setObjectName(f"configField_{name}")
            self.editors[name] = editor
            self.annotations[name] = annotation
            self.form_layout.addField(field_label(name), editor, name)
            self._connect_editor(editor)
        if self._window_action_form:
            geometry = self.editors.get("geometry")
            if isinstance(geometry, TupleFieldEditor):
                geometry.mode_combo.setMaximumWidth(88)
                for part in geometry.value_editors:
                    part.setMaximumWidth(62)
            operation = self.editors.get("operation")
            if isinstance(operation, QComboBox):
                operation.currentIndexChanged.connect(self._update_window_action_fields)
            self._update_window_action_fields()
        region_editor = self.editors.get("region")
        if isinstance(region_editor, TupleFieldEditor):
            region_editor.pick_button.clicked.connect(self._pick_region)
        template_editor = self.editors.get("template_path")
        if isinstance(template_editor, PathFieldEditor):
            template_editor.capture_button.clicked.connect(self._capture_template)
        launch_path_editor = self.editors.get("path")
        if self._launch_action_form and isinstance(launch_path_editor, PathFieldEditor):
            launch_path_editor.fileSelected.connect(self._launch_file_selected)
        self.set_advanced_visible(show_advanced)

    def _connect_editor(self, editor: QWidget) -> None:
        if isinstance(editor, QCheckBox):
            editor.toggled.connect(self._emit_changed)
        elif isinstance(editor, (QSpinBox, QDoubleSpinBox)):
            editor.valueChanged.connect(self._emit_changed)
        elif isinstance(editor, QComboBox):
            editor.currentIndexChanged.connect(self._emit_changed)
        elif isinstance(editor, (TupleFieldEditor, PathFieldEditor)):
            editor.changed.connect(self._emit_changed)
        elif isinstance(editor, QLineEdit):
            editor.textChanged.connect(self._emit_changed)

    def _emit_changed(self) -> None:
        self.changed.emit()

    def _update_window_action_fields(self) -> None:
        operation = self.editors.get("operation")
        geometry = self.editors.get("geometry")
        if isinstance(operation, QComboBox) and geometry is not None:
            self.form_layout.setFieldVisible(
                geometry,
                operation.currentData() == "move_resize",
            )

    def _pick_region(self) -> None:
        if self._pick_region_callback is None:
            return
        try:
            region = self._pick_region_callback(self._capture_target())
        except Exception as error:
            self._report_error(str(error))
            return
        if region is None:
            return
        editor = self.editors.get("region")
        if isinstance(editor, TupleFieldEditor):
            editor.setValue(region)

    def _capture_template(self) -> None:
        if self._capture_template_callback is None:
            return
        try:
            captured = self._capture_template_callback(self._capture_target())
        except Exception as error:
            self._report_error(str(error))
            return
        if captured is None:
            return
        region_editor = self.editors.get("region")
        if isinstance(region_editor, TupleFieldEditor):
            region_editor.setValue(captured.region)
        path_editor = self.editors.get("template_path")
        if isinstance(path_editor, PathFieldEditor):
            path_editor.setText(str(captured.path))

    def _capture_target(self) -> str:
        editor = self.editors.get("target")
        if isinstance(editor, QLineEdit):
            return editor.text().strip() or "desktop"
        if isinstance(editor, QComboBox):
            value = editor.currentData()
            return str(value) if value else "desktop"
        return "desktop"

    def _launch_file_selected(self, selected: str) -> None:
        selection = launch_file_selection(
            Path(selected),
            python_executable=default_python_executable(),
            comspec=default_comspec(),
        )
        path_editor = self.editors.get("path")
        arguments_editor = self.editors.get("arguments")
        working_directory_editor = self.editors.get("working_directory")
        if not (
            isinstance(path_editor, PathFieldEditor)
            and isinstance(arguments_editor, QLineEdit)
            and isinstance(working_directory_editor, PathFieldEditor)
        ):
            return
        current_arguments = json.loads(arguments_editor.text() or "[]")
        arguments = replace_automatic_prefix(
            current_arguments,
            self._launch_automatic_arguments,
            selection.arguments,
        )
        current_working_directory = working_directory_editor.text().strip()
        previous_auto_directory = (
            str(self._launch_automatic_working_directory)
            if self._launch_automatic_working_directory is not None
            else ""
        )
        editors = (path_editor, arguments_editor, working_directory_editor)
        previous_signal_states = [editor.blockSignals(True) for editor in editors]
        try:
            path_editor.setText(str(selection.path))
            arguments_editor.setText(json.dumps(arguments, ensure_ascii=False))
            if (
                not current_working_directory
                or current_working_directory == previous_auto_directory
            ):
                working_directory_editor.setText(str(selection.working_directory))
        finally:
            for editor, previous_state in zip(editors, previous_signal_states, strict=True):
                editor.blockSignals(previous_state)
        self._launch_automatic_arguments = selection.arguments
        self._launch_automatic_working_directory = selection.working_directory
        self.changed.emit()

    def _infer_launch_automatic_values(self) -> None:
        if not self._launch_action_form:
            return
        path_editor = self.editors.get("path")
        arguments_editor = self.editors.get("arguments")
        working_directory_editor = self.editors.get("working_directory")
        if not (
            isinstance(path_editor, PathFieldEditor)
            and isinstance(arguments_editor, QLineEdit)
            and isinstance(working_directory_editor, PathFieldEditor)
        ):
            return
        arguments = json.loads(arguments_editor.text() or "[]")
        prefix = infer_automatic_prefix(Path(path_editor.text()), arguments)
        self._launch_automatic_arguments = prefix
        self._launch_automatic_working_directory = None
        if not prefix:
            return
        automatic_directory = Path(prefix[-1]).resolve().parent
        current_directory = working_directory_editor.text().strip()
        if current_directory and Path(current_directory).resolve() == automatic_directory:
            self._launch_automatic_working_directory = automatic_directory

    def editor(self, name: str) -> QWidget:
        return self.editors[name]

    def set_binding_options(self, options: tuple[ResultBindingOption, ...]) -> None:
        self._binding_options = options
        for name, editor in self.editors.items():
            if not isinstance(editor, TupleFieldEditor):
                continue
            field = _binding_field_for_tuple(name, len(editor.value_editors))
            editor.binding_selector.set_options(
                tuple(option for option in options if option.field == field)
            )

    def set_advanced_visible(self, visible: bool) -> None:
        self._show_advanced = visible
        for name in self._advanced_fields:
            editor = self.editors[name]
            self.form_layout.setFieldVisible(editor, visible)

    def advanced_non_default_count(self) -> int:
        values = self.values()
        count = 0
        for name in self._advanced_fields:
            field = self.model_type.model_fields[name]
            current = values[name]
            if field.is_required():
                count += current not in (None, "", [], {})
                continue
            default = field.get_default(call_default_factory=True)
            count += current != default
        return count

    def values(self) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for name, editor in self.editors.items():
            annotation = self.annotations[name]
            if isinstance(editor, QCheckBox):
                values[name] = editor.isChecked()
            elif isinstance(editor, (QSpinBox, QDoubleSpinBox)):
                values[name] = editor.value()
            elif isinstance(editor, QComboBox):
                values[name] = editor.currentData()
            elif isinstance(editor, TupleFieldEditor):
                values[name] = editor.value()
            elif isinstance(editor, PathFieldEditor):
                text = editor.text().strip()
                values[name] = (
                    text or None
                    if _allows_none(self.model_type.model_fields[name].annotation)
                    else text
                )
            elif isinstance(editor, QLineEdit):
                text = editor.text().strip()
                if not text and _allows_none(self.model_type.model_fields[name].annotation):
                    values[name] = None
                elif _is_plain_text(annotation):
                    values[name] = text
                else:
                    values[name] = json.loads(text)
        return values

    def set_values(self, values: dict[str, Any]) -> None:
        for name, value in values.items():
            editor = self.editors.get(name)
            if editor is None:
                continue
            annotation = self.annotations[name]
            if isinstance(editor, QCheckBox):
                editor.setChecked(bool(value))
            elif isinstance(editor, QSpinBox):
                editor.setValue(int(value))
            elif isinstance(editor, QDoubleSpinBox):
                editor.setValue(float(value))
            elif isinstance(editor, QComboBox):
                index = editor.findData(value)
                if index >= 0:
                    editor.setCurrentIndex(index)
            elif isinstance(editor, TupleFieldEditor):
                editor.setValue(value)
            elif isinstance(editor, PathFieldEditor):
                editor.clear() if value is None else editor.setText(str(value))
            elif isinstance(editor, QLineEdit):
                if value is None:
                    editor.clear()
                elif _is_plain_text(annotation):
                    editor.setText(str(value))
                else:
                    editor.setText(json.dumps(value, ensure_ascii=False))
        self._infer_launch_automatic_values()


def _create_editor(
    name: str,
    annotation: Any,
    default: Any,
    optional: bool,
    *,
    allow_pick: bool,
    allow_capture: bool,
    file_filter: str,
) -> QWidget:
    if get_origin(annotation) is tuple:
        return TupleFieldEditor(
            annotation,
            default,
            optional=optional,
            allow_pick=allow_pick and name == "region",
        )
    if annotation is Path:
        return PathFieldEditor(
            default,
            allow_capture=allow_capture and name == "template_path",
            file_filter=file_filter,
        )
    if optional:
        line = QLineEdit()
        if default is not None:
            line.setText(
                str(default)
                if _is_plain_text(annotation)
                else json.dumps(default, ensure_ascii=False)
            )
        return line
    origin = get_origin(annotation)
    if origin is Literal:
        combo = FocusWheelComboBox()
        for choice in get_args(annotation):
            combo.addItem(choice_label(choice), choice)
        _select_combo_default(combo, default)
        return combo
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        enum_combo = FocusWheelComboBox()
        for choice in annotation:
            enum_combo.addItem(choice_label(choice), choice)
        _select_combo_default(enum_combo, default)
        return enum_combo
    if annotation is bool:
        checkbox = QCheckBox()
        checkbox.setChecked(bool(default))
        return checkbox
    if annotation is int:
        integer = FocusWheelSpinBox()
        integer.setRange(-(2**31), 2**31 - 1)
        if default is not None:
            integer.setValue(int(default))
        return integer
    if annotation is float:
        number = FocusWheelDoubleSpinBox()
        number.setRange(-1_000_000_000.0, 1_000_000_000.0)
        number.setDecimals(4)
        if default is not None:
            number.setValue(float(default))
        return number
    text_editor = QLineEdit()
    if default is not None:
        text_editor.setText(
            str(default) if _is_plain_text(annotation) else json.dumps(default, ensure_ascii=False)
        )
    elif not optional and not _is_plain_text(annotation):
        text_editor.setPlaceholderText("JSON")
    return text_editor


def _binding_field_for_tuple(name: str, length: int) -> str:
    if name in {"position", "offset"} or length == 2:
        return "position"
    return "bounds"


def _tuple_arguments(annotation: Any) -> tuple[Any, ...]:
    arguments = get_args(annotation)
    if not arguments or arguments[-1:] == (Ellipsis,):
        raise TypeError("tuple fields must have a fixed number of values")
    if any(argument not in {int, float} for argument in arguments):
        raise TypeError("tuple field values must be numeric")
    return arguments


def _create_number_editor(annotation: Any) -> QSpinBox | QDoubleSpinBox:
    if annotation is int:
        integer = FocusWheelSpinBox()
        integer.setRange(-(2**31), 2**31 - 1)
        return integer
    number = FocusWheelDoubleSpinBox()
    number.setRange(-1_000_000_000.0, 1_000_000_000.0)
    number.setDecimals(4)
    return number


def _zero_tuple(arguments: tuple[Any, ...]) -> tuple[int | float, ...]:
    return tuple(0 if argument is int else 0.0 for argument in arguments)


def _unwrap_optional(annotation: Any) -> tuple[Any, bool]:
    origin = get_origin(annotation)
    if origin in {Union, UnionType}:
        arguments = get_args(annotation)
        without_none = tuple(item for item in arguments if item is not type(None))
        if len(without_none) == 1 and len(without_none) != len(arguments):
            return without_none[0], True
    return annotation, False


def _allows_none(annotation: Any) -> bool:
    return type(None) in get_args(annotation)


def _is_plain_text(annotation: Any) -> bool:
    return annotation in {str, Path, Any}


def _select_combo_default(editor: QComboBox, default: Any) -> None:
    if default is None:
        return
    index = editor.findData(default)
    if index >= 0:
        editor.setCurrentIndex(index)

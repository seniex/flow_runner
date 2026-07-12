import json
from enum import Enum
from pathlib import Path
from types import UnionType
from typing import Any, Literal, Union, get_args, get_origin

from pydantic import BaseModel
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QWidget,
)


class TupleFieldEditor(QWidget):
    def __init__(
        self,
        annotation: Any,
        default: Any = None,
        *,
        optional: bool = False,
    ) -> None:
        super().__init__()
        self.setProperty("fieldKind", "tuple")
        self._optional = optional
        self._arguments = _tuple_arguments(annotation)
        self.mode_combo = QComboBox()
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
        self.binding_edit = QLineEdit()
        self.binding_edit.setPlaceholderText("$result.primary.position")
        self.binding_edit.setProperty("fieldKind", "binding")
        self.pages = QStackedWidget()
        if optional:
            self.pages.addWidget(QWidget())
        self.pages.addWidget(self.value_container)
        self.pages.addWidget(self.binding_edit)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.mode_combo)
        layout.addWidget(self.pages, 1)
        self.mode_combo.currentIndexChanged.connect(self.pages.setCurrentIndex)
        if default is None and optional:
            self.mode_combo.setCurrentIndex(self.mode_combo.findData("none"))
        else:
            self.setValue(default if default is not None else _zero_tuple(self._arguments))

    def value(self) -> tuple[int | float, ...] | str | None:
        mode = self.mode_combo.currentData()
        if mode == "none":
            return None
        if mode == "binding":
            return self.binding_edit.text().strip()
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
        self.binding_edit.setText(expression)
        self.mode_combo.setCurrentIndex(self.mode_combo.findData("binding"))


class PathFieldEditor(QWidget):
    def __init__(self, default: Any = None) -> None:
        super().__init__()
        self.setProperty("fieldKind", "path")
        self.line_edit = QLineEdit()
        self.browse_button = QPushButton("选择…")
        self.browse_button.setProperty("role", "browse")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.line_edit, 1)
        layout.addWidget(self.browse_button)
        self.browse_button.clicked.connect(self._browse)
        if default is not None:
            self.setText(str(default))

    def text(self) -> str:
        return self.line_edit.text()

    def setText(self, value: str) -> None:  # noqa: N802 - Qt-compatible API
        self.line_edit.setText(value)

    def clear(self) -> None:
        self.line_edit.clear()

    def _browse(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "选择文件", self.text())
        if path:
            self.setText(path)


class ModelForm(QWidget):
    def __init__(self, model_type: type[BaseModel]) -> None:
        super().__init__()
        self.model_type = model_type
        self.editors: dict[str, QWidget] = {}
        self.annotations: dict[str, Any] = {}
        layout = QFormLayout(self)
        for name, field in model_type.model_fields.items():
            annotation, optional = _unwrap_optional(field.annotation)
            default = None if field.is_required() else field.get_default(call_default_factory=True)
            editor = _create_editor(annotation, default, optional)
            editor.setObjectName(f"configField_{name}")
            self.editors[name] = editor
            self.annotations[name] = annotation
            layout.addRow(name, editor)

    def editor(self, name: str) -> QWidget:
        return self.editors[name]

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


def _create_editor(annotation: Any, default: Any, optional: bool) -> QWidget:
    if get_origin(annotation) is tuple:
        return TupleFieldEditor(annotation, default, optional=optional)
    if annotation is Path:
        return PathFieldEditor(default)
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
        combo = QComboBox()
        for choice in get_args(annotation):
            combo.addItem(str(choice), choice)
        _select_combo_default(combo, default)
        return combo
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        enum_combo = QComboBox()
        for choice in annotation:
            enum_combo.addItem(str(choice.value), choice)
        _select_combo_default(enum_combo, default)
        return enum_combo
    if annotation is bool:
        checkbox = QCheckBox()
        checkbox.setChecked(bool(default))
        return checkbox
    if annotation is int:
        integer = QSpinBox()
        integer.setRange(-(2**31), 2**31 - 1)
        if default is not None:
            integer.setValue(int(default))
        return integer
    if annotation is float:
        number = QDoubleSpinBox()
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


def _tuple_arguments(annotation: Any) -> tuple[Any, ...]:
    arguments = get_args(annotation)
    if not arguments or arguments[-1:] == (Ellipsis,):
        raise TypeError("tuple fields must have a fixed number of values")
    if any(argument not in {int, float} for argument in arguments):
        raise TypeError("tuple field values must be numeric")
    return arguments


def _create_number_editor(annotation: Any) -> QSpinBox | QDoubleSpinBox:
    if annotation is int:
        integer = QSpinBox()
        integer.setRange(-(2**31), 2**31 - 1)
        return integer
    number = QDoubleSpinBox()
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

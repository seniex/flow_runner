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
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QWidget,
)


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
            elif isinstance(editor, QLineEdit):
                text = editor.text().strip()
                if not text and _allows_none(self.model_type.model_fields[name].annotation):
                    values[name] = None
                elif _is_plain_text(annotation):
                    values[name] = text
                else:
                    values[name] = json.loads(text)
        return values


def _create_editor(annotation: Any, default: Any, optional: bool) -> QWidget:
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

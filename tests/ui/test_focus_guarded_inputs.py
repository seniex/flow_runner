import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QLineEdit, QScrollArea, QVBoxLayout, QWidget

from flow_runner.ui.editors.model_form import TupleFieldEditor
from flow_runner.ui.editors.policy_editor import PolicyEditor
from flow_runner.ui.widgets import (
    FocusWheelComboBox,
    FocusWheelDoubleSpinBox,
    FocusWheelSpinBox,
)


@pytest.mark.parametrize(
    "widget_type",
    [FocusWheelComboBox, FocusWheelSpinBox, FocusWheelDoubleSpinBox],
)
def test_focus_guarded_input_does_not_accept_wheel_focus(qtbot, widget_type):
    widget = widget_type()
    qtbot.addWidget(widget)

    assert widget.focusPolicy() == Qt.FocusPolicy.StrongFocus


def _send_wheel(widget: QWidget, delta: int) -> QWheelEvent:
    global_center = widget.mapToGlobal(widget.rect().center())
    receiver: QWidget | None = widget
    while receiver is not None:
        event = QWheelEvent(
            QPointF(receiver.mapFromGlobal(global_center)),
            QPointF(global_center),
            QPoint(),
            QPoint(0, delta),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.ScrollUpdate,
            False,
        )
        QApplication.sendEvent(receiver, event)
        QApplication.processEvents()
        if event.isAccepted():
            return event
        receiver = receiver.parentWidget()
    return event


def _scrolling_policy_editor(qtbot):
    scroll = QScrollArea()
    scroll.resize(320, 180)
    content = QWidget()
    layout = QVBoxLayout(content)
    focus_target = QLineEdit()
    layout.addWidget(focus_target)
    layout.addSpacing(300)
    editor = PolicyEditor()
    layout.addWidget(editor)
    layout.addSpacing(600)
    scroll.setWidget(content)
    scroll.setWidgetResizable(True)
    qtbot.addWidget(scroll)
    scroll.show()
    QApplication.processEvents()
    return scroll, focus_target, editor


def test_unfocused_spin_box_ignores_wheel_and_scrolls_parent(qtbot):
    scroll, focus_target, editor = _scrolling_policy_editor(qtbot)
    spin = editor.max_attempts_spin
    spin.setValue(10)
    focus_target.setFocus()
    scroll.verticalScrollBar().setValue(250)
    before_scroll = scroll.verticalScrollBar().value()

    _send_wheel(spin, -120)

    assert spin.value() == 10
    assert scroll.verticalScrollBar().value() > before_scroll


def test_focused_spin_box_accepts_wheel(qtbot):
    scroll, _focus_target, editor = _scrolling_policy_editor(qtbot)
    spin = editor.max_attempts_spin
    spin.setValue(10)
    spin.setFocus()
    assert spin.hasFocus()

    _send_wheel(spin, -120)

    assert spin.value() == 9
    assert scroll.verticalScrollBar().value() == 0


def test_unfocused_combo_box_does_not_change_selection(qtbot):
    scroll, focus_target, editor = _scrolling_policy_editor(qtbot)
    combo = editor.mode_combo
    combo.setCurrentIndex(0)
    focus_target.setFocus()
    scroll.verticalScrollBar().setValue(250)

    _send_wheel(combo, -120)

    assert combo.currentIndex() == 0


def test_tuple_numeric_editor_uses_focus_guarded_wheel(qtbot):
    container = QWidget()
    layout = QVBoxLayout(container)
    focus_target = QLineEdit()
    tuple_editor = TupleFieldEditor(tuple[int, int], (10, 20))
    layout.addWidget(focus_target)
    layout.addWidget(tuple_editor)
    qtbot.addWidget(container)
    container.show()
    focus_target.setFocus()
    QApplication.processEvents()

    _send_wheel(tuple_editor.value_editors[0], -120)

    assert tuple_editor.value() == (10, 20)

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel

from flow_runner.ui.widgets.responsive_controls import ColumnContainer, ResponsiveControlArea


def test_responsive_action_group_wraps_and_unwraps_with_width(qtbot):
    area = ResponsiveControlArea()
    qtbot.addWidget(area)
    group = area.add_group("步骤")
    actions = [QAction(text, area) for text in ("新增步骤", "复制步骤", "删除步骤")]
    buttons = [group.add_action(action) for action in actions]

    area.resize(170, 300)
    area.show()
    qtbot.wait(1)
    narrow_rows = {button.geometry().top() for button in buttons}

    area.resize(600, 120)
    qtbot.wait(1)
    wide_rows = {button.geometry().top() for button in buttons}

    assert len(narrow_rows) > len(wide_rows)
    assert len(wide_rows) == 1


def test_responsive_action_button_tracks_qaction_state(qtbot):
    area = ResponsiveControlArea()
    qtbot.addWidget(area)
    action = QAction("保存", area)
    button = area.add_group("项目").add_action(action)
    calls = []
    action.triggered.connect(lambda: calls.append("saved"))

    action.setEnabled(False)
    assert not button.isEnabled()
    action.setEnabled(True)
    button.click()

    assert calls == ["saved"]


def test_column_container_keeps_content_above_controls(qtbot):
    content = QLabel("内容")
    controls = ResponsiveControlArea()
    column = ColumnContainer(content, controls, object_name="testColumn")
    qtbot.addWidget(column)

    assert column.content is content
    assert column.controls is controls
    assert column.layout().stretch(0) == 1

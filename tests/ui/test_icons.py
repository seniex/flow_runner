from PySide6.QtCore import Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QToolButton

from flow_runner.app import create_application
from flow_runner.domain.enums import RunnerState
from flow_runner.domain.project import AutomationStep, FlowGroup, Project, Workflow
from flow_runner.infrastructure.persistence.project_store import ProjectStore
from flow_runner.ui.icons import ACTION_ICON_NAMES, application_icon, icon
from flow_runner.ui.main_window import MainWindow


def sample_project() -> Project:
    workflow = Workflow(name="流程", steps=[AutomationStep(name="步骤")])
    return Project(name="项目", groups=[FlowGroup(name="组", workflows=[workflow])])


def test_declared_icons_are_loadable():
    assert ACTION_ICON_NAMES["pauseRecordingAction"] == "pause"
    assert ACTION_ICON_NAMES["openRecordingDirectoryAction"] == "folder-open"
    assert not application_icon().isNull()
    for name in set(ACTION_ICON_NAMES.values()):
        assert not icon(name).isNull(), name


def test_application_and_window_icons_are_set(qtbot, tmp_path):
    project_path = tmp_path / "project.json"
    ProjectStore(project_path).save(sample_project())
    composition = create_application([], project_path=project_path)
    qtbot.addWidget(composition.window)

    assert not composition.app.windowIcon().isNull()
    assert composition.window.windowIcon().cacheKey() == composition.app.windowIcon().cacheKey()

    composition.shutdown()


def test_main_window_common_actions_keep_text_and_icons(qtbot):
    window = MainWindow(sample_project())
    qtbot.addWidget(window)
    actions = {
        action.objectName(): action
        for action in window.findChildren(QAction)
        if action.objectName() in ACTION_ICON_NAMES
    }

    assert set(actions) == set(ACTION_ICON_NAMES)
    assert all(action.text() and not action.icon().isNull() for action in actions.values())
    buttons = window.findChildren(QToolButton)
    assert buttons
    assert all(
        button.toolButtonStyle()
        is (
            Qt.ToolButtonStyle.ToolButtonIconOnly
            if button.defaultAction() is window.open_recording_directory_action
            else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
        )
        for button in buttons
        if button.defaultAction() in actions.values()
    )


def test_pause_action_switches_to_resume_icon(qtbot):
    window = MainWindow(sample_project())
    qtbot.addWidget(window)
    pause_key = window.pause_action.icon().cacheKey()

    window._update_runtime_actions(RunnerState.PAUSED)

    assert window.pause_action.text() == "继续"
    assert window.pause_action.icon().cacheKey() != pause_key

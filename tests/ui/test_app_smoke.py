import pytest
from pydantic import ValidationError

from flow_runner.app import create_application
from flow_runner.domain.project import Project
from flow_runner.infrastructure.persistence.project_store import ProjectStore
from flow_runner.ui.hotkeys import HotkeyConfig


def test_application_starts_offscreen_with_injected_project_path(qtbot, tmp_path):
    path = tmp_path / "project.json"
    ProjectStore(path).save(Project(name="测试项目"))

    composition = create_application([], project_path=path)
    qtbot.addWidget(composition.window)

    assert composition.window.view_model.project.name == "测试项目"
    assert composition.window.styleSheet() == ""
    assert composition.app.styleSheet()


def test_duplicate_hotkeys_are_rejected():
    with pytest.raises(ValidationError, match="duplicate"):
        HotkeyConfig(start="F6", stop="F6")


def test_empty_hotkey_disables_the_action():
    config = HotkeyConfig(start="", stop="F7", pause="", record="")
    assert config.enabled_bindings() == {"F7": "stop"}

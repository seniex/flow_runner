import pytest
from pydantic import ValidationError

from flow_runner.app import create_application
from flow_runner.domain.project import Project
from flow_runner.infrastructure.persistence.project_store import ProjectStore
from flow_runner.ui.hotkeys import HotkeyConfig, HotkeyService


def test_application_starts_offscreen_with_injected_project_path(qtbot, tmp_path):
    path = tmp_path / "project.json"
    ProjectStore(path).save(Project(name="测试项目"))

    composition = create_application([], project_path=path)
    qtbot.addWidget(composition.window)

    assert composition.window.view_model.project.name == "测试项目"
    assert composition.window.styleSheet() == ""
    assert composition.app.styleSheet()
    assert {item.name for item in composition.registry.condition_metadata()} >= {
        "vision.ocr",
        "vision.image",
        "vision.pixel",
    }
    assert composition.runner_bridge.runner is composition.runner
    assert {item.name for item in composition.registry.action_metadata()} >= {
        "input.mouse",
        "input.keyboard",
        "system.wait",
        "variables.set",
        "system.launch",
        "recording.playback",
        "system.window_action",
    }


def test_duplicate_hotkeys_are_rejected():
    with pytest.raises(ValidationError, match="duplicate"):
        HotkeyConfig(start="F6", stop="F6")


def test_empty_hotkey_disables_the_action():
    config = HotkeyConfig(start="", stop="F7", pause="", record="")
    assert config.enabled_bindings() == {"F7": "stop"}


def test_hotkey_service_dispatches_and_stops_injected_listener():
    calls = []

    class Listener:
        def __init__(self, on_press):
            self.on_press = on_press
            self.started = False
            self.stopped = False

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

    created = []

    def factory(on_press):
        listener = Listener(on_press)
        created.append(listener)
        return listener

    service = HotkeyService(
        HotkeyConfig(start="F6", stop="", pause="", record=""),
        actions={"start": lambda: calls.append("start")},
        listener_factory=factory,
    )
    service.start()
    created[0].on_press("f6")
    service.stop()

    assert calls == ["start"]
    assert created[0].started and created[0].stopped

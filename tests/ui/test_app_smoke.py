import pytest
from pydantic import ValidationError

from flow_runner.app import create_application
from flow_runner.domain.project import FlowGroup, Project, Workflow
from flow_runner.infrastructure.ocr.paddle_json import PaddleJsonOcr
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
        "system.window",
        "system.process",
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


def test_application_hotkeys_start_selected_workflow_and_stop_on_shutdown(qtbot, tmp_path):
    workflow = Workflow(name="main")
    project = Project(name="p", groups=[FlowGroup(name="g", workflows=[workflow])])
    path = tmp_path / "project.json"
    ProjectStore(path).save(project)
    created = []

    class Listener:
        def __init__(self, on_press):
            self.on_press = on_press
            self.started = False
            self.stopped = False

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

    def factory(on_press):
        listener = Listener(on_press)
        created.append(listener)
        return listener

    composition = create_application(
        [],
        project_path=path,
        hotkey_config=HotkeyConfig(start="F6", stop="", pause="", record=""),
        hotkey_listener_factory=factory,
    )
    qtbot.addWidget(composition.window)
    composition.window.flow_tree.select_workflow(workflow.id)
    composition.start_services()

    with qtbot.waitSignal(composition.runner_bridge.finished, timeout=3000):
        created[0].on_press("f6")
    composition.shutdown()

    assert created[0].started and created[0].stopped


def test_record_hotkey_toggles_capture_and_saves_latest_recording(qtbot, tmp_path):
    hotkey_listeners = []
    recording_callbacks = {}

    class Listener:
        def __init__(self, on_press=None):
            self.on_press = on_press
            self.started = False
            self.stopped = False

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

    def hotkey_factory(on_press):
        listener = Listener(on_press)
        hotkey_listeners.append(listener)
        return listener

    recording_listener = Listener()

    def recording_factory(**callbacks):
        recording_callbacks.update(callbacks)
        return recording_listener

    path = tmp_path / "latest.json"
    composition = create_application(
        [],
        project_path=tmp_path / "project.json",
        hotkey_config=HotkeyConfig(start="", stop="", pause="", record="F9"),
        hotkey_listener_factory=hotkey_factory,
        recording_listener_factory=recording_factory,
        recording_path=path,
    )
    qtbot.addWidget(composition.window)
    composition.start_services()

    hotkey_listeners[0].on_press("f9")
    recording_callbacks["on_move"](8, 9)
    hotkey_listeners[0].on_press("f9")
    composition.shutdown()

    assert recording_listener.started and recording_listener.stopped
    assert path.exists()


def test_application_save_action_persists_property_edits(qtbot, tmp_path):
    from flow_runner.domain.project import AutomationStep

    workflow = Workflow(name="main", steps=[AutomationStep(name="old")])
    project = Project(name="p", groups=[FlowGroup(name="g", workflows=[workflow])])
    path = tmp_path / "project.json"
    ProjectStore(path).save(project)
    composition = create_application([], project_path=path)
    qtbot.addWidget(composition.window)
    composition.window.flow_tree.select_workflow(workflow.id)
    composition.window.step_list.select_step(workflow.steps[0].id)

    composition.window.property_panel.name_edit.setText("new")
    composition.window.property_panel.apply_button.click()
    composition.window.save_action.trigger()

    assert ProjectStore(path).load().groups[0].workflows[0].steps[0].name == "new"
    assert not composition.window.view_model.dirty


def test_application_selects_paddle_ocr_from_project_settings(qtbot, tmp_path):
    executable = tmp_path / "PaddleOCR-json.exe"
    executable.write_bytes(b"")
    path = tmp_path / "project.json"
    ProjectStore(path).save(
        Project(
            name="p",
            settings={
                "ocr_engine": "paddle",
                "paddle_exe_path": str(executable),
            },
        )
    )

    composition = create_application([], project_path=path)
    qtbot.addWidget(composition.window)

    assert composition.ocr_client is not None
    assert composition.ocr_client.executable == executable.resolve()
    assert isinstance(composition.registry.condition("vision.ocr").engine, PaddleJsonOcr)


def test_application_loads_hotkeys_from_project_settings(qtbot, tmp_path):
    created = []

    class Listener:
        def __init__(self, on_press):
            self.on_press = on_press

        def start(self):
            pass

        def stop(self):
            pass

    def factory(on_press):
        listener = Listener(on_press)
        created.append(listener)
        return listener

    path = tmp_path / "project.json"
    ProjectStore(path).save(
        Project(
            name="p",
            settings={"hotkeys": {"start": "F10", "stop": "", "pause": "", "record": ""}},
        )
    )
    composition = create_application([], project_path=path, hotkey_listener_factory=factory)
    qtbot.addWidget(composition.window)
    composition.start_services()

    assert composition.hotkey_service.bindings == {"F10": "start"}

import json
from uuid import uuid4

import pytest
from pydantic import ValidationError
from PySide6.QtGui import QKeySequence

from flow_runner.app import create_application
from flow_runner.domain.enums import ConditionOutcome, StepOutcome
from flow_runner.domain.errors import ConfigurationError
from flow_runner.domain.project import AutomationStep, FlowGroup, Project, Workflow
from flow_runner.domain.routing import (
    ComparisonOperator,
    RouteRule,
    RouteTarget,
    RouteTargetKind,
)
from flow_runner.engine.runner import Runner
from flow_runner.infrastructure.capture.targets import TargetCapture, WindowCaptureMode
from flow_runner.infrastructure.ocr.paddle_json import PaddleJsonOcr
from flow_runner.infrastructure.persistence.project_store import ProjectStore
from flow_runner.ui.dialogs.settings_dialog import SettingsDialog
from flow_runner.ui.hotkeys import HotkeyConfig, HotkeyService
from flow_runner.ui.runner_bridge import RunnerBridge


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


def test_runner_bridge_shutdown_reports_success_when_idle():
    bridge = RunnerBridge(Runner(object()))

    assert bridge.shutdown(timeout_seconds=0.01) is True


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


def test_application_releases_held_inputs_when_runtime_terminates(qtbot, tmp_path):
    workflow = Workflow(name="main")
    project = Project(name="p", groups=[FlowGroup(name="g", workflows=[workflow])])
    path = tmp_path / "project.json"
    ProjectStore(path).save(project)

    class Device:
        def __init__(self):
            self.releases = 0

        def release_all(self):
            self.releases += 1

    mouse = Device()
    keyboard = Device()
    composition = create_application(
        [],
        project_path=path,
        mouse_device=mouse,
        keyboard_device=keyboard,
    )
    qtbot.addWidget(composition.window)
    composition.window.flow_tree.select_workflow(workflow.id)

    with qtbot.waitSignal(composition.runner_bridge.terminated, timeout=3000):
        composition.window.start_action.trigger()

    assert mouse.releases == 1
    assert keyboard.releases == 1


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


def test_ctrl_s_commits_all_pending_step_editors_and_mixed_actions(qtbot, tmp_path):
    step = AutomationStep.model_validate(
        {
            "name": "old",
            "condition": {
                "id": "detector",
                "capability": "vision.ocr",
                "config": {"keywords": "旧文字"},
            },
            "actions": [
                {
                    "capability": "input.mouse",
                    "config": {"operation": "click", "position": [100, 200]},
                },
                {
                    "capability": "input.keyboard",
                    "config": {"operation": "press", "key": "q"},
                },
                {"capability": "system.wait", "config": {"seconds": 0.5}},
            ],
            "condition_policy": {"mode": "until", "max_attempts": 5},
            "routes": [{"outcome": "success", "target": {"kind": "end"}}],
        }
    )
    workflow = Workflow(name="main", steps=[step])
    path = tmp_path / "project.json"
    ProjectStore(path).save(Project(name="p", groups=[FlowGroup(name="g", workflows=[workflow])]))
    composition = create_application([], project_path=path)
    window = composition.window
    qtbot.addWidget(window)
    window.show()
    window.flow_tree.select_workflow(workflow.id)
    window.step_list.select_step(step.id)
    panel = window.property_panel

    panel.name_edit.setText("new")
    panel.condition_editor.config_form.editor("keywords").setText("新文字")
    panel.action_editor.config_form.editor("settle_delay").setValue(0.75)
    panel.policy_editor.interval_spin.setValue(2.5)
    panel.route_editor.outcome_combo.setCurrentIndex(
        panel.route_editor.outcome_combo.findData(StepOutcome.TIMEOUT)
    )

    assert panel.has_pending_edits
    assert window.save_action.isEnabled()
    assert (
        window.save_shortcut.key().matches(QKeySequence(QKeySequence.StandardKey.Save))
        is QKeySequence.SequenceMatch.ExactMatch
    )
    window.save_shortcut.activated.emit()

    saved = ProjectStore(path).load().groups[0].workflows[0].steps[0]
    assert saved.name == "new"
    assert saved.condition.config["keywords"] == "新文字"
    assert [action.capability for action in saved.actions] == [
        "input.mouse",
        "input.keyboard",
        "system.wait",
    ]
    assert saved.actions[0].config["settle_delay"] == 0.75
    assert saved.condition_policy.interval_seconds == 2.5
    assert saved.routes[0].outcome is StepOutcome.TIMEOUT
    assert not panel.has_pending_edits
    assert not window.view_model.dirty
    assert str(path) in window.statusBar().currentMessage()


def test_ctrl_s_deletes_action_without_rebuilding_independently_loaded_route(qtbot, tmp_path):
    target = Workflow(name="target")
    step = AutomationStep.model_validate(
        {
            "name": "game over",
            "actions": [
                {
                    "capability": "input.mouse",
                    "config": {"operation": "click", "position": [100, 200]},
                },
                {
                    "capability": "input.mouse",
                    "config": {"operation": "click", "position": [300, 400]},
                },
            ],
            "routes": [
                RouteRule(
                    outcome=StepOutcome.SUCCESS,
                    target=RouteTarget.jump_workflow(target.id),
                )
            ],
        }
    )
    workflow = Workflow(name="main", steps=[step])
    path = tmp_path / "project.json"
    ProjectStore(path).save(
        Project(name="p", groups=[FlowGroup(name="g", workflows=[workflow, target])])
    )
    composition = create_application([], project_path=path)
    window = composition.window
    qtbot.addWidget(window)
    window.flow_tree.select_workflow(workflow.id)
    window.step_list.select_step(step.id)

    window.property_panel.action_editor.action_list.setCurrentRow(0)
    window.property_panel.action_editor.remove_button.click()
    window.save_shortcut.activated.emit()

    saved = ProjectStore(path).load().groups[0].workflows[0].steps[0]
    assert [action.config["position"] for action in saved.actions] == [[300, 400]]
    assert saved.routes == step.routes
    assert "项目已保存" in window.statusBar().currentMessage()


def test_ctrl_s_commits_mixed_parameter_edits_without_rebuilding_route(
    qtbot,
    tmp_path,
    monkeypatch,
):
    step = AutomationStep.model_validate(
        {
            "name": "mixed",
            "condition": {
                "id": "detector",
                "capability": "vision.ocr",
                "config": {"keywords": "old"},
            },
            "actions": [
                {
                    "capability": "input.mouse",
                    "config": {"operation": "click", "position": [100, 200]},
                },
                {
                    "capability": "input.keyboard",
                    "config": {"operation": "press", "key": "q"},
                },
                {"capability": "system.wait", "config": {"seconds": 0.5}},
            ],
            "routes": [{"outcome": "success", "target": {"kind": "end"}}],
        }
    )
    workflow = Workflow(name="main", steps=[step])
    path = tmp_path / "project.json"
    ProjectStore(path).save(Project(name="p", groups=[FlowGroup(name="g", workflows=[workflow])]))
    composition = create_application([], project_path=path)
    window = composition.window
    qtbot.addWidget(window)
    window.flow_tree.select_workflow(workflow.id)
    window.step_list.select_step(step.id)
    panel = window.property_panel
    monkeypatch.setattr(
        panel.route_editor,
        "_current_route",
        lambda: pytest.fail("untouched route editor was rebuilt"),
    )

    panel.action_editor.config_form.editor("settle_delay").setValue(0.25)
    panel.action_editor.action_list.setCurrentRow(1)
    panel.action_editor.config_form.editor("key").setText("w")
    panel.action_editor.action_list.setCurrentRow(2)
    panel.action_editor.config_form.editor("seconds").setValue(1.25)
    panel.condition_editor.config_form.editor("keywords").setText("new")
    panel.policy_editor.interval_spin.setValue(2.0)
    window.save_shortcut.activated.emit()

    saved = ProjectStore(path).load().groups[0].workflows[0].steps[0]
    assert saved.actions[0].config["settle_delay"] == 0.25
    assert saved.actions[1].config["key"] == "w"
    assert saved.actions[2].config["seconds"] == 1.25
    assert saved.condition.config["keywords"] == "new"
    assert saved.condition_policy.interval_seconds == 2.0
    assert saved.routes == step.routes


def test_ctrl_s_reports_specific_pending_route_validation_error(qtbot, tmp_path):
    step = AutomationStep(
        name="step",
        routes=[RouteRule(outcome=StepOutcome.SUCCESS, target=RouteTarget.end())],
    )
    workflow = Workflow(name="main", steps=[step])
    target = Workflow(name="target")
    path = tmp_path / "project.json"
    ProjectStore(path).save(
        Project(name="p", groups=[FlowGroup(name="g", workflows=[workflow, target])])
    )
    composition = create_application([], project_path=path)
    window = composition.window
    qtbot.addWidget(window)
    window.flow_tree.select_workflow(workflow.id)
    window.step_list.select_step(step.id)
    editor = window.property_panel.route_editor
    editor.target_combo.setCurrentIndex(editor.target_combo.findData(RouteTargetKind.JUMP_WORKFLOW))
    editor.workflow_combo.setCurrentIndex(-1)

    window.save_shortcut.activated.emit()

    assert window.statusBar().currentMessage() == (
        "项目保存失败：路由“成功 → 跳转流程”未选择目标流程"
    )


def test_ctrl_s_reports_project_reference_error_without_clearing_pending_edit(qtbot, tmp_path):
    step = AutomationStep(
        name="step",
        routes=[RouteRule(outcome=StepOutcome.SUCCESS, target=RouteTarget.end())],
    )
    workflow = Workflow(name="main", steps=[step])
    path = tmp_path / "project.json"
    ProjectStore(path).save(Project(name="p", groups=[FlowGroup(name="g", workflows=[workflow])]))
    composition = create_application([], project_path=path)
    window = composition.window
    qtbot.addWidget(window)
    window.flow_tree.select_workflow(workflow.id)
    window.step_list.select_step(step.id)
    window.property_panel.routes_edit.setPlainText(
        json.dumps(
            [
                {
                    "outcome": "success",
                    "target": {"kind": "jump_workflow", "workflow_id": str(uuid4())},
                }
            ]
        )
    )

    window.save_shortcut.activated.emit()

    assert "references missing workflow" in window.statusBar().currentMessage()
    assert window.property_panel.has_pending_edits
    saved = ProjectStore(path).load().groups[0].workflows[0].steps[0]
    assert saved.routes == step.routes


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


def test_application_configures_background_window_capture_from_project_settings(
    qtbot,
    tmp_path,
):
    path = tmp_path / "project.json"
    ProjectStore(path).save(
        Project(
            name="p",
            settings={
                "window_capture_mode": "background",
                "window_capture_fallback": False,
                "window_capture_timeout_seconds": 1.25,
            },
        )
    )

    composition = create_application([], project_path=path)
    qtbot.addWidget(composition.window)
    capture = composition.resource_coordinator.perception.capture

    assert isinstance(capture, TargetCapture)
    assert capture.default_window_mode is WindowCaptureMode.BACKGROUND
    assert not capture.fallback_to_foreground
    assert capture.background_window.timeout_seconds == 1.25


@pytest.mark.parametrize(
    "settings",
    [
        {"window_capture_mode": "unknown"},
        {"window_capture_timeout_seconds": 0},
        {"window_capture_fallback": "false"},
    ],
)
def test_application_rejects_invalid_window_capture_settings(tmp_path, settings):
    path = tmp_path / "project.json"
    ProjectStore(path).save(Project(name="p", settings=settings))

    with pytest.raises(ConfigurationError, match="window capture"):
        create_application([], project_path=path)


def test_settings_dialog_round_trips_window_capture_options(qtbot):
    dialog = SettingsDialog(
        HotkeyConfig(),
        {
            "window_capture_mode": "background",
            "window_capture_fallback": False,
            "window_capture_timeout_seconds": 1.5,
        },
    )
    qtbot.addWidget(dialog)
    assert dialog.window_capture_mode_combo.currentData() == "background"
    assert not dialog.window_capture_fallback_check.isChecked()
    dialog.window_capture_timeout_spin.setValue(2.25)

    settings = dialog.project_settings()

    assert settings["window_capture_mode"] == "background"
    assert settings["window_capture_fallback"] is False
    assert settings["window_capture_timeout_seconds"] == 2.25


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


def test_application_condition_preview_does_not_run_full_workflow(qtbot, tmp_path):
    step = AutomationStep.model_validate(
        {
            "name": "preview",
            "condition": {
                "id": "count",
                "capability": "runtime.count",
                "config": {
                    "counter": "step",
                    "target_id": "00000000-0000-0000-0000-000000000001",
                    "operator": ComparisonOperator.EQ,
                    "expected": 0,
                },
            },
        }
    )
    workflow = Workflow(name="main", steps=[step])
    path = tmp_path / "project.json"
    ProjectStore(path).save(Project(name="p", groups=[FlowGroup(name="g", workflows=[workflow])]))
    composition = create_application([], project_path=path)
    qtbot.addWidget(composition.window)
    composition.window.flow_tree.select_workflow(workflow.id)
    composition.window.step_list.select_step(step.id)

    with qtbot.waitSignal(composition.runner_bridge.finished, timeout=3000) as blocker:
        composition.window.preview_action.trigger()

    assert blocker.args[0].outcome is ConditionOutcome.MATCH


def test_application_rejects_invalid_registered_capability_config(tmp_path):
    path = tmp_path / "project.json"
    ProjectStore(path).save(
        Project(
            name="invalid",
            groups=[
                FlowGroup(
                    name="g",
                    workflows=[
                        Workflow(
                            name="w",
                            steps=[
                                AutomationStep.model_validate(
                                    {
                                        "name": "bad wait",
                                        "actions": [
                                            {
                                                "capability": "system.wait",
                                                "config": {"seconds": -1},
                                            }
                                        ],
                                    }
                                )
                            ],
                        )
                    ],
                )
            ],
        )
    )

    with pytest.raises(ConfigurationError, match="system.wait"):
        create_application([], project_path=path)


def test_application_save_boundary_revalidates_capability_configs(qtbot, tmp_path):
    path = tmp_path / "project.json"
    ProjectStore(path).save(Project(name="valid"))
    composition = create_application([], project_path=path)
    qtbot.addWidget(composition.window)
    invalid = Project(
        name="invalid",
        groups=[
            FlowGroup(
                name="g",
                workflows=[
                    Workflow(
                        name="w",
                        steps=[
                            AutomationStep.model_validate(
                                {
                                    "name": "bad wait",
                                    "actions": [
                                        {
                                            "capability": "system.wait",
                                            "config": {"seconds": -1},
                                        }
                                    ],
                                }
                            )
                        ],
                    )
                ],
            )
        ],
    )

    with pytest.raises(ConfigurationError, match="system.wait"):
        composition.window.save_project(invalid)

    assert ProjectStore(path).load().name == "valid"

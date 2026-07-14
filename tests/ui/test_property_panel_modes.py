import json

from PySide6.QtCore import QSettings

from flow_runner.capabilities.actions.wait import WaitActionConfig
from flow_runner.capabilities.conditions.ocr import OcrConditionConfig
from flow_runner.capabilities.registry import CapabilityRegistry
from flow_runner.domain.actions import ActionSpec
from flow_runner.domain.conditions import LeafCondition
from flow_runner.domain.enums import ConditionMode, StepOutcome
from flow_runner.domain.policies import ActionPolicy, ConditionPolicy
from flow_runner.domain.project import AutomationStep, Project
from flow_runner.domain.routing import RouteRule, RouteTarget
from flow_runner.ui.editor_preferences import EditorPreferences
from flow_runner.ui.panels.property_panel import PropertyPanel


class _Capability:
    def __init__(self, name, config_model):
        self.name = name
        self.config_model = config_model


def _registry():
    registry = CapabilityRegistry()
    registry.register_condition(_Capability("vision.ocr", OcrConditionConfig))
    registry.register_action(_Capability("system.wait", WaitActionConfig))
    return registry


def _step():
    return AutomationStep(
        name="检测并等待",
        condition=LeafCondition(
            id="ocr",
            capability="vision.ocr",
            config={"keywords": "旧文字"},
        ),
        actions=[ActionSpec(capability="system.wait", config={"seconds": 1.0})],
        condition_policy=ConditionPolicy(
            mode=ConditionMode.UNTIL,
            interval_seconds=1.0,
            max_attempts=3,
        ),
        action_policy=ActionPolicy(max_attempts=2, retry_interval_seconds=0.5),
        routes=[RouteRule(outcome=StepOutcome.SUCCESS, target=RouteTarget.end())],
    )


def _panel(qtbot, **kwargs):
    panel = PropertyPanel(_registry(), Project(name="p"), **kwargs)
    qtbot.addWidget(panel)
    panel.set_step(_step())
    panel.resize(700, 600)
    panel.show()
    return panel


def test_property_panel_defaults_to_common_tab_and_hides_raw_json(qtbot):
    panel = _panel(qtbot)

    assert panel.mode_tabs.currentWidget() is panel.common_tab
    assert not panel.condition_edit.isVisibleTo(panel)

    panel.mode_tabs.setCurrentWidget(panel.advanced_json_tab)

    assert panel.condition_edit.isVisibleTo(panel)


def test_switching_to_advanced_json_commits_and_serializes_guided_edits(qtbot):
    panel = _panel(qtbot)
    panel.condition_editor.config_form.editor("keywords").setText("新文字")
    panel.action_editor.config_form.editor("seconds").setValue(2.5)
    panel.policy_editor.interval_spin.setValue(3.0)
    panel.route_editor.outcome_combo.setCurrentIndex(
        panel.route_editor.outcome_combo.findData(StepOutcome.TIMEOUT)
    )

    panel.mode_tabs.setCurrentWidget(panel.advanced_json_tab)

    assert json.loads(panel.condition_edit.toPlainText())["config"]["keywords"] == "新文字"
    assert json.loads(panel.actions_edit.toPlainText())[0]["config"]["seconds"] == 2.5
    assert json.loads(panel.condition_policy_edit.toPlainText())["interval_seconds"] == 3.0
    assert json.loads(panel.routes_edit.toPlainText())[0]["outcome"] == "timeout"


def test_switching_from_valid_json_loads_all_guided_editors(qtbot):
    panel = _panel(qtbot)
    panel.mode_tabs.setCurrentWidget(panel.advanced_json_tab)
    panel.condition_edit.setPlainText(
        json.dumps(
            {
                "id": "ocr",
                "capability": "vision.ocr",
                "config": {"keywords": "JSON文字", "language": "eng"},
            }
        )
    )
    panel.actions_edit.setPlainText(
        json.dumps([{"capability": "system.wait", "config": {"seconds": 4.0}}])
    )
    panel.condition_policy_edit.setPlainText(
        json.dumps({"mode": "until", "interval_seconds": 5.0, "max_attempts": 6})
    )
    panel.action_policy_edit.setPlainText(
        json.dumps({"max_attempts": 3, "retry_interval_seconds": 1.5})
    )
    panel.routes_edit.setPlainText(json.dumps([{"outcome": "failure", "target": {"kind": "end"}}]))

    panel.mode_tabs.setCurrentWidget(panel.common_tab)

    assert panel.mode_tabs.currentWidget() is panel.common_tab
    assert panel.condition_editor.condition().config["keywords"] == "JSON文字"
    assert panel.action_editor.action_specs()[0].config["seconds"] == 4.0
    condition_policy, action_policy = panel.policy_editor.policies()
    assert condition_policy.interval_seconds == 5.0
    assert action_policy.retry_interval_seconds == 1.5
    assert panel.route_editor.routes()[0].outcome is StepOutcome.FAILURE


def test_invalid_json_keeps_advanced_tab_and_preserves_guided_state(qtbot):
    panel = _panel(qtbot)
    panel.mode_tabs.setCurrentWidget(panel.advanced_json_tab)
    panel.condition_edit.setPlainText("{")

    panel.mode_tabs.setCurrentWidget(panel.common_tab)

    assert panel.mode_tabs.currentWidget() is panel.advanced_json_tab
    assert panel.validation_error
    assert panel.condition_editor.condition().config["keywords"] == "旧文字"


def test_advanced_field_preference_updates_dynamic_forms_and_persists(qtbot, tmp_path):
    settings = QSettings(str(tmp_path / "editor.ini"), QSettings.Format.IniFormat)
    preferences = EditorPreferences(settings)
    panel = _panel(qtbot, editor_preferences=preferences)

    assert not panel.show_advanced_check.isChecked()
    assert panel.condition_editor.config_form.editor("language").isHidden()

    panel.show_advanced_check.setChecked(True)

    assert not panel.condition_editor.config_form.editor("language").isHidden()
    assert preferences.show_advanced

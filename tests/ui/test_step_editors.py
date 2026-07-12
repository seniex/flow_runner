from pathlib import Path

from flow_runner.capabilities.conditions.image import ImageConditionConfig
from flow_runner.capabilities.conditions.ocr import OcrConditionConfig
from flow_runner.capabilities.registry import CapabilityRegistry
from flow_runner.domain.actions import ActionSpec
from flow_runner.domain.enums import ConditionMode, StepOutcome
from flow_runner.domain.project import AutomationStep
from flow_runner.domain.routing import RouteRule, RouteTarget
from flow_runner.ui.dialogs.guided_add_dialog import GuidedAddDialog
from flow_runner.ui.editors.action_editor import ActionEditor
from flow_runner.ui.editors.condition_editor import switch_condition_capability
from flow_runner.ui.editors.policy_editor import PolicyEditor
from flow_runner.ui.editors.route_editor import RouteEditor


class Capability:
    def __init__(self, name, config_model):
        self.name = name
        self.config_model = config_model

    async def evaluate(self, config, context):
        raise NotImplementedError

    def required_resources(self, config):
        return frozenset()

    async def execute(self, config, context):
        raise NotImplementedError


def registry():
    result = CapabilityRegistry()
    result.register_condition(Capability("vision.ocr", OcrConditionConfig))
    result.register_condition(Capability("vision.image", ImageConditionConfig))
    result.register_action(Capability("system.wait", OcrConditionConfig))
    return result


def test_switching_ocr_to_image_preserves_common_fields_policy_and_routes():
    route = RouteRule(outcome=StepOutcome.SUCCESS, target=RouteTarget.end())
    step = AutomationStep.model_validate(
        {
            "name": "检测",
            "condition": {
                "id": "screen",
                "capability": "vision.ocr",
                "config": {
                    "target": "desktop",
                    "region": [1, 2, 30, 40],
                    "keywords": "开始",
                },
            },
            "condition_policy": {"mode": "until", "max_attempts": 5},
            "routes": [route],
        }
    )

    switched, discarded = switch_condition_capability(
        step,
        "vision.image",
        ImageConditionConfig,
        required_config={"template_path": Path("target.png")},
    )

    assert switched.condition.capability == "vision.image"
    assert switched.condition.config["region"] == (1, 2, 30, 40)
    assert switched.condition_policy == step.condition_policy
    assert switched.routes == step.routes
    assert discarded == {"keywords": "开始"}


def test_guided_dialog_builds_a_valid_detection_step(qtbot):
    dialog = GuidedAddDialog(registry())
    qtbot.addWidget(dialog)

    step = dialog.build_step(
        category="检测",
        capability="vision.ocr",
        config={"keywords": "开始"},
    )

    assert step.condition.capability == "vision.ocr"
    assert step.actions == []


def test_guided_dialog_builds_execution_and_control_steps(qtbot):
    dialog = GuidedAddDialog(registry())
    qtbot.addWidget(dialog)

    execution = dialog.build_step(
        category="执行",
        capability="system.wait",
        config={"keywords": "等待"},
    )
    control = dialog.build_step(category="控制", capability="end", config={})

    assert execution.condition is None
    assert execution.actions == [
        ActionSpec(
            capability="system.wait",
            config={
                "keywords": "等待",
                "target": "desktop",
                "region": None,
                "language": "chi_sim",
                "preprocessing": "",
            },
        )
    ]
    assert control.condition is None
    assert control.actions == []
    assert control.routes[0].outcome is StepOutcome.SUCCESS
    assert control.routes[0].target == RouteTarget.end()


def test_guided_dialog_category_switches_available_capabilities(qtbot):
    dialog = GuidedAddDialog(registry())
    qtbot.addWidget(dialog)

    dialog.category_combo.setCurrentText("执行")

    assert dialog.capability_combo.itemData(0) == "system.wait"


def test_guided_dialog_accepts_json_config_and_returns_step(qtbot):
    dialog = GuidedAddDialog(registry())
    qtbot.addWidget(dialog)
    index = dialog.capability_combo.findData("vision.ocr")
    dialog.capability_combo.setCurrentIndex(index)
    dialog.config_edit.setPlainText('{"keywords": "开始"}')

    dialog.accept()

    assert dialog.result() == GuidedAddDialog.DialogCode.Accepted
    assert dialog.step().condition.capability == "vision.ocr"


def test_policy_editor_exposes_once_and_until(qtbot):
    editor = PolicyEditor()
    qtbot.addWidget(editor)

    editor.set_mode(ConditionMode.UNTIL)

    assert editor.mode() is ConditionMode.UNTIL
    assert editor.mode_combo.count() == 2


def test_action_and_route_editors_round_trip_models(qtbot):
    actions = ActionEditor(registry())
    routes = RouteEditor()
    qtbot.addWidget(actions)
    qtbot.addWidget(routes)
    action = ActionSpec(capability="system.wait", config={"keywords": "x"})
    route = RouteRule(outcome=StepOutcome.SUCCESS, target=RouteTarget.end())

    actions.set_actions([action])
    routes.set_routes([route])

    assert actions.action_specs() == [action]
    assert actions.capability_combo.itemData(0) == "system.wait"
    assert routes.routes() == [route]

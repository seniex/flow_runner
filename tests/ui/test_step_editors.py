from pathlib import Path

from flow_runner.capabilities.conditions.image import ImageConditionConfig
from flow_runner.capabilities.conditions.ocr import OcrConditionConfig
from flow_runner.capabilities.registry import CapabilityRegistry
from flow_runner.domain.enums import ConditionMode, StepOutcome
from flow_runner.domain.project import AutomationStep
from flow_runner.domain.routing import RouteRule, RouteTarget
from flow_runner.ui.dialogs.guided_add_dialog import GuidedAddDialog
from flow_runner.ui.editors.condition_editor import switch_condition_capability
from flow_runner.ui.editors.policy_editor import PolicyEditor


class Capability:
    def __init__(self, name, config_model):
        self.name = name
        self.config_model = config_model

    async def evaluate(self, config, context):
        raise NotImplementedError

    def required_resources(self, config):
        return frozenset()


def registry():
    result = CapabilityRegistry()
    result.register_condition(Capability("vision.ocr", OcrConditionConfig))
    result.register_condition(Capability("vision.image", ImageConditionConfig))
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


def test_policy_editor_exposes_once_and_until(qtbot):
    editor = PolicyEditor()
    qtbot.addWidget(editor)

    editor.set_mode(ConditionMode.UNTIL)

    assert editor.mode() is ConditionMode.UNTIL
    assert editor.mode_combo.count() == 2

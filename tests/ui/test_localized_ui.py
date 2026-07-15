from enum import Enum
from typing import Literal, get_args, get_origin

from PySide6.QtWidgets import QLabel, QLineEdit

from flow_runner.capabilities.actions.keyboard import KeyboardActionConfig
from flow_runner.capabilities.actions.mouse import MouseActionConfig
from flow_runner.capabilities.actions.process import LaunchProcessConfig
from flow_runner.capabilities.actions.script import PlaybackScriptConfig
from flow_runner.capabilities.actions.variables import SetVariableConfig
from flow_runner.capabilities.actions.wait import WaitActionConfig
from flow_runner.capabilities.actions.window import WindowActionConfig
from flow_runner.capabilities.conditions.count import CountConditionConfig
from flow_runner.capabilities.conditions.image import ImageConditionConfig
from flow_runner.capabilities.conditions.ocr import OcrConditionConfig
from flow_runner.capabilities.conditions.pixel import PixelConditionConfig
from flow_runner.capabilities.conditions.process import ProcessConditionConfig
from flow_runner.capabilities.conditions.region_change import RegionChangeConditionConfig
from flow_runner.capabilities.conditions.time import TimeConditionConfig
from flow_runner.capabilities.conditions.variables import VariableConditionConfig
from flow_runner.capabilities.conditions.window import WindowConditionConfig
from flow_runner.capabilities.registry import CapabilityRegistry
from flow_runner.domain.actions import ActionSpec
from flow_runner.domain.conditions import LeafCondition
from flow_runner.domain.project import AutomationStep, Project
from flow_runner.ui.editors.action_editor import ActionEditor
from flow_runner.ui.localization import action_summary, choice_label, field_label
from flow_runner.ui.panels.property_panel import PropertyPanel
from flow_runner.ui.panels.step_list_panel import StepCardWidget
from flow_runner.ui.result_bindings import result_binding_options

ALL_UI_CONFIG_MODELS = (
    MouseActionConfig,
    KeyboardActionConfig,
    LaunchProcessConfig,
    PlaybackScriptConfig,
    SetVariableConfig,
    WaitActionConfig,
    WindowActionConfig,
    CountConditionConfig,
    ImageConditionConfig,
    OcrConditionConfig,
    PixelConditionConfig,
    ProcessConditionConfig,
    RegionChangeConditionConfig,
    TimeConditionConfig,
    VariableConditionConfig,
    WindowConditionConfig,
)

KNOWN_FIELD_NAMES = {name for model in ALL_UI_CONFIG_MODELS for name in model.model_fields}


class Capability:
    def __init__(self, name, config_model):
        self.name = name
        self.config_model = config_model

    def required_resources(self, config):
        del config
        return frozenset()


def literal_or_enum_choices(annotation: object) -> tuple[object, ...]:
    origin = get_origin(annotation)
    if origin is Literal:
        return get_args(annotation)
    if isinstance(annotation, type) and issubclass(annotation, Enum):
        return tuple(annotation)
    return tuple(
        choice
        for argument in get_args(annotation)
        if argument is not type(None)
        for choice in literal_or_enum_choices(argument)
    )


def test_every_registered_config_field_has_a_chinese_or_approved_technical_label():
    missing = {name for name in KNOWN_FIELD_NAMES if field_label(name) == name}
    assert missing == set()


def test_every_ui_choice_has_a_localized_label():
    choices = {
        choice
        for model in ALL_UI_CONFIG_MODELS
        for field in model.model_fields.values()
        for choice in literal_or_enum_choices(field.annotation)
    }
    missing = {value for value in choices if choice_label(value) == str(value)}
    assert missing == set()


def test_mouse_coordinate_fields_and_choices_are_localized():
    assert field_label("coordinate_space") == "坐标空间"
    assert choice_label("screen") == "绝对屏幕坐标"
    assert choice_label("target") == "目标相对坐标"


def test_normal_binding_controls_do_not_expose_internal_result_syntax(qtbot):
    capabilities = CapabilityRegistry()
    capabilities.register_condition(Capability("vision.ocr", OcrConditionConfig))
    capabilities.register_action(Capability("input.mouse", MouseActionConfig))
    panel = PropertyPanel(capabilities, Project(name="p"))
    qtbot.addWidget(panel)
    panel.set_step(
        AutomationStep(
            name="点击登录",
            condition=LeafCondition(
                id="登录按钮",
                capability="vision.ocr",
                config={"keywords": "登录"},
            ),
            actions=[
                ActionSpec(
                    capability="input.mouse",
                    config={"operation": "click", "position": "$result.primary.position"},
                )
            ],
        )
    )
    panel.show()
    qtbot.wait(1)

    visible_text = "\n".join(
        widget.text() for widget in panel.findChildren(QLineEdit) if widget.isVisible()
    )
    assert "$result." not in visible_text


def test_action_summaries_use_friendly_binding_names(qtbot):
    condition = LeafCondition(
        id="登录按钮",
        capability="vision.ocr",
        config={"keywords": "登录"},
    )
    action = ActionSpec(
        capability="input.mouse",
        config={"operation": "click", "position": "$result.primary.position"},
    )
    options = result_binding_options(condition)
    labels = {option.expression: option.label for option in options}

    assert action_summary(action, binding_labels=labels) == (
        "鼠标：左键点击 当前步骤检测结果 → 主要结果 → 坐标"
    )

    editor = ActionEditor(
        _registry_with_visual_capabilities(),
    )
    qtbot.addWidget(editor)
    editor.set_binding_options(options)
    editor.set_actions([action])
    assert "$result." not in editor.action_list.item(0).text()
    assert "当前步骤检测结果 → 主要结果 → 坐标" in editor.action_list.item(0).text()

    card = StepCardWidget(
        AutomationStep(name="点击登录", condition=condition, actions=[action]),
        1,
    )
    qtbot.addWidget(card)
    card_text = "\n".join(label.text() for label in card.findChildren(QLabel))
    assert "$result." not in card_text
    assert "当前步骤检测结果 → 主要结果 → 坐标" in card_text


def _registry_with_visual_capabilities() -> CapabilityRegistry:
    capabilities = CapabilityRegistry()
    capabilities.register_condition(Capability("vision.ocr", OcrConditionConfig))
    capabilities.register_action(Capability("input.mouse", MouseActionConfig))
    return capabilities

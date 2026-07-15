from flow_runner.capabilities.actions.mouse import MouseActionConfig
from flow_runner.capabilities.conditions.ocr import OcrConditionConfig
from flow_runner.capabilities.registry import CapabilityRegistry
from flow_runner.domain.actions import ActionSpec
from flow_runner.domain.conditions import ConditionGroup, LeafCondition
from flow_runner.domain.enums import StepOutcome
from flow_runner.domain.project import AutomationStep, Project
from flow_runner.domain.routing import (
    ComparisonOperator,
    RoutePredicate,
    RouteRule,
    RouteTarget,
    RouteTargetKind,
)
from flow_runner.ui.editors.action_editor import ActionEditor
from flow_runner.ui.editors.model_form import BindingFieldEditor, ModelForm, TupleFieldEditor
from flow_runner.ui.editors.route_editor import RouteEditor
from flow_runner.ui.panels.property_panel import PropertyPanel
from flow_runner.ui.result_bindings import result_binding_options


class Capability:
    def __init__(self, name, config_model):
        self.name = name
        self.config_model = config_model

    def required_resources(self, config):
        del config
        return frozenset()


def registry():
    result = CapabilityRegistry()
    result.register_condition(Capability("vision.ocr", OcrConditionConfig))
    result.register_action(Capability("input.mouse", MouseActionConfig))
    return result


def test_binding_options_use_capability_and_condition_node_names():
    condition = ConditionGroup(
        id="可点击目标",
        operator="or",
        children=[
            LeafCondition(
                id="登录按钮",
                capability="vision.ocr",
                config={"keywords": "登录"},
            ),
            LeafCondition(
                id="开始图片",
                capability="vision.image",
                config={"template_path": "a.png"},
            ),
        ],
    )

    options = result_binding_options(condition)
    labels = {option.expression: option.label for option in options}

    assert labels["$result.primary.position"] == "当前步骤检测结果 → 主要结果 → 坐标"
    assert labels['$result.children["登录按钮"].text'] == "OCR 文字检测「登录按钮」→ 识别文字"
    assert labels['$result.children["开始图片"].position'] == "图片模板检测「开始图片」→ 坐标"


def test_binding_field_preserves_unknown_expression_as_custom(qtbot):
    editor = BindingFieldEditor()
    qtbot.addWidget(editor)
    editor.set_options(())
    editor.setValue('$result.children["旧节点"].text')

    assert editor.is_custom
    assert editor.value() == '$result.children["旧节点"].text'


def test_mouse_position_binding_shows_chinese_and_preserves_expression(qtbot):
    condition = LeafCondition(
        id="登录按钮",
        capability="vision.ocr",
        config={"keywords": "登录"},
    )
    form = ModelForm(MouseActionConfig)
    qtbot.addWidget(form)
    form.set_binding_options(result_binding_options(condition))

    position = form.editor("position")
    assert isinstance(position, TupleFieldEditor)
    position.setBinding("$result.primary.position")

    assert position.binding_selector.combo.currentText() == "当前步骤检测结果 → 主要结果 → 坐标"
    assert form.values()["position"] == "$result.primary.position"


def test_action_and_route_editors_preserve_binding_options_and_serialization(qtbot):
    condition = LeafCondition(
        id="登录按钮",
        capability="vision.ocr",
        config={"keywords": "登录"},
    )
    options = result_binding_options(condition)
    actions = ActionEditor(registry())
    routes = RouteEditor()
    qtbot.addWidget(actions)
    qtbot.addWidget(routes)

    actions.set_binding_options(options)
    position = actions.config_form.editor("position")
    assert isinstance(position, TupleFieldEditor)
    position.setBinding("$result.primary.position")
    actions.add_button.click()

    routes.set_binding_options(options)
    routes.target_combo.setCurrentIndex(routes.target_combo.findData(RouteTargetKind.END))
    routes.predicate_source_combo.setCurrentIndex(
        routes.predicate_source_combo.findData("binding")
    )
    routes.predicate_binding_editor.setValue("$result.primary.text")
    routes.predicate_expected_edit.setText('"登录"')
    routes.add_button.click()

    assert actions.action_specs()[0].config["position"] == "$result.primary.position"
    assert routes.routes()[0].predicate == RoutePredicate(
        source="binding",
        key="$result.primary.text",
        operator=ComparisonOperator.EQ,
        expected="登录",
    )
    assert routes.predicate_binding_editor.combo.currentText().endswith("识别文字")


def test_property_panel_propagates_named_condition_bindings(qtbot):
    condition = ConditionGroup(
        id="全部条件",
        operator="and",
        children=[
            LeafCondition(
                id="登录按钮",
                capability="vision.ocr",
                config={"keywords": "登录"},
            )
        ],
    )
    expression = '$result.children["登录按钮"].position'
    step = AutomationStep(
        name="点击登录",
        condition=condition,
        actions=[
            ActionSpec(
                capability="input.mouse",
                config={"operation": "click", "position": expression},
            )
        ],
        routes=[
            RouteRule(
                outcome=StepOutcome.SUCCESS,
                predicate=RoutePredicate.binding(expression, ComparisonOperator.EQ, [10, 20]),
                target=RouteTarget.end(),
            )
        ],
    )
    panel = PropertyPanel(registry(), Project(name="p"))
    qtbot.addWidget(panel)

    panel.set_step(step)

    position = panel.action_editor.config_form.editor("position")
    assert isinstance(position, TupleFieldEditor)
    expected_label = "OCR 文字检测「登录按钮」→ 坐标"
    assert position.binding_selector.combo.currentText() == expected_label
    assert panel.route_editor.predicate_binding_editor.combo.currentText() == expected_label
    assert position.value() == expression
    assert panel.route_editor.routes()[0].predicate.key == expression

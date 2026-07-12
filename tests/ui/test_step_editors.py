from pathlib import Path

import pytest

from flow_runner.capabilities.actions.mouse import MouseActionConfig
from flow_runner.capabilities.conditions.image import ImageConditionConfig
from flow_runner.capabilities.conditions.ocr import OcrConditionConfig
from flow_runner.capabilities.registry import CapabilityRegistry
from flow_runner.domain.actions import ActionSpec
from flow_runner.domain.conditions import ConditionGroup, LeafCondition
from flow_runner.domain.enums import ConditionMode, StepOutcome
from flow_runner.domain.policies import ActionPolicy, ConditionPolicy
from flow_runner.domain.project import AutomationStep, FlowGroup, Project, Workflow
from flow_runner.domain.routing import (
    ComparisonOperator,
    RoutePredicate,
    RouteRule,
    RouteTarget,
    RouteTargetKind,
)
from flow_runner.ui.dialogs.guided_add_dialog import GuidedAddDialog
from flow_runner.ui.editors.action_editor import ActionEditor
from flow_runner.ui.editors.condition_editor import ConditionEditor, switch_condition_capability
from flow_runner.ui.editors.model_form import ModelForm, PathFieldEditor, TupleFieldEditor
from flow_runner.ui.editors.policy_editor import PolicyEditor
from flow_runner.ui.editors.route_editor import RouteEditor
from flow_runner.ui.panels.property_panel import PropertyPanel


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


def test_condition_editor_guides_named_children_in_composite_tree(qtbot):
    editor = ConditionEditor(registry())
    qtbot.addWidget(editor)
    condition = ConditionGroup(
        id="all",
        operator="and",
        children=[
            LeafCondition(
                id="ocr_a",
                capability="vision.ocr",
                config={"keywords": "开始"},
            ),
            LeafCondition(
                id="image_b",
                capability="vision.image",
                config={"template_path": Path("button.png")},
            ),
        ],
    )

    editor.set_condition(condition)
    image_item = editor.tree.topLevelItem(0).child(1)
    editor.tree.setCurrentItem(image_item)
    editor.node_id_edit.setText("button_image")

    edited = editor.condition()

    assert isinstance(edited, ConditionGroup)
    assert edited.operator == "and"
    assert [child.id for child in edited.children] == ["ocr_a", "button_image"]
    assert editor.message_label.text() == ""


def test_condition_editor_wraps_leaf_in_or_group_without_json(qtbot):
    editor = ConditionEditor(registry())
    qtbot.addWidget(editor)
    editor.set_condition(
        LeafCondition(
            id="ocr_a",
            capability="vision.ocr",
            config={"keywords": "开始"},
        )
    )

    editor.add_or_button.click()

    condition = editor.condition()
    assert isinstance(condition, ConditionGroup)
    assert condition.operator == "or"
    assert condition.children[0].id == "ocr_a"
    assert len(condition.children) == 2


def test_condition_editor_validates_every_leaf_before_apply(qtbot):
    editor = ConditionEditor(registry())
    qtbot.addWidget(editor)
    editor.set_condition(
        ConditionGroup(
            id="all",
            operator="and",
            children=[
                LeafCondition(
                    id="ocr_a",
                    capability="vision.ocr",
                    config={"keywords": "开始"},
                ),
                LeafCondition(
                    id="image_b",
                    capability="vision.image",
                    config={},
                ),
            ],
        )
    )

    with pytest.raises(ValueError, match="image_b"):
        editor.condition()


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


def test_guided_dialog_selects_control_target_without_uuid_json(qtbot):
    target_step = AutomationStep(name="目标步骤")
    current = Workflow(name="当前流程", steps=[target_step])
    other = Workflow(name="其他流程")
    project = Project(
        name="p",
        groups=[FlowGroup(name="组", workflows=[current, other])],
    )
    dialog = GuidedAddDialog(registry(), project, current_workflow_id=current.id)
    qtbot.addWidget(dialog)
    dialog.category_combo.setCurrentText("控制")
    dialog.capability_combo.setCurrentIndex(dialog.capability_combo.findData("next_step"))
    dialog.control_step_combo.setCurrentIndex(dialog.control_step_combo.findData(target_step.id))

    dialog.accept()

    assert dialog.result() == GuidedAddDialog.DialogCode.Accepted
    assert dialog.step().routes[0].target == RouteTarget.next_step(target_step.id)


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


def test_model_form_builds_editors_from_pydantic_fields(qtbot):
    form = ModelForm(OcrConditionConfig)
    qtbot.addWidget(form)

    form.editor("keywords").setText("开始")
    values = form.values()

    assert values["keywords"] == "开始"
    assert values["target"] == "desktop"
    assert values["region"] is None


def test_model_form_uses_focused_region_coordinate_and_path_editors(qtbot):
    ocr_form = ModelForm(OcrConditionConfig)
    image_form = ModelForm(ImageConditionConfig)
    mouse_form = ModelForm(MouseActionConfig)
    qtbot.addWidget(ocr_form)
    qtbot.addWidget(image_form)
    qtbot.addWidget(mouse_form)

    region = ocr_form.editor("region")
    template_path = image_form.editor("template_path")
    position = mouse_form.editor("position")

    assert isinstance(region, TupleFieldEditor)
    assert isinstance(template_path, PathFieldEditor)
    assert isinstance(position, TupleFieldEditor)
    region.setValue((1, 2, 30, 40))
    template_path.setText("button.png")
    position.setBinding("$result.primary.position")

    assert ocr_form.values()["region"] == (1, 2, 30, 40)
    assert image_form.values()["template_path"] == "button.png"
    assert mouse_form.values()["position"] == "$result.primary.position"


def test_guided_dialog_builds_step_from_generated_form(qtbot):
    dialog = GuidedAddDialog(registry())
    qtbot.addWidget(dialog)
    index = dialog.capability_combo.findData("vision.ocr")
    dialog.capability_combo.setCurrentIndex(index)
    dialog.config_form.editor("keywords").setText("开始")

    dialog.accept()

    assert dialog.result() == GuidedAddDialog.DialogCode.Accepted
    assert dialog.step().condition.config["keywords"] == "开始"


def test_policy_editor_exposes_once_and_until(qtbot):
    editor = PolicyEditor()
    qtbot.addWidget(editor)

    editor.set_mode(ConditionMode.UNTIL)

    assert editor.mode() is ConditionMode.UNTIL
    assert editor.mode_combo.count() == 2


def test_policy_editor_preserves_tick_hooks_when_editing_limits(qtbot):
    editor = PolicyEditor()
    qtbot.addWidget(editor)
    hook = ActionSpec(capability="system.wait", config={"keywords": "x"})
    editor.set_policies(
        ConditionPolicy(
            mode=ConditionMode.UNTIL,
            max_attempts=2,
            before_attempt_actions=[hook],
        ),
        ActionPolicy(max_attempts=2, retry_interval_seconds=0.5),
    )
    editor.max_attempts_spin.setValue(5)

    condition, action = editor.policies()

    assert condition.max_attempts == 5
    assert condition.before_attempt_actions == [hook]
    assert action.max_attempts == 2


def test_policy_editor_guides_before_and_after_attempt_actions(qtbot):
    editor = PolicyEditor(registry())
    qtbot.addWidget(editor)
    before = ActionSpec(
        capability="system.wait",
        config=OcrConditionConfig(keywords="轮询前").model_dump(mode="python"),
    )
    after = ActionSpec(
        capability="system.wait",
        config=OcrConditionConfig(keywords="未命中").model_dump(mode="python"),
    )
    editor.set_policies(
        ConditionPolicy(
            mode=ConditionMode.UNTIL,
            max_attempts=2,
            before_attempt_actions=[before],
            after_no_match_actions=[after],
        ),
        ActionPolicy(),
    )

    editor.before_actions_editor.config_form.editor("keywords").setText("更新后的轮询前")
    editor.before_actions_editor.update_button.click()
    condition, _action = editor.policies()

    assert condition.before_attempt_actions[0].config["keywords"] == "更新后的轮询前"
    assert condition.after_no_match_actions == [after]


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


def test_action_editor_adds_action_from_generated_config_form(qtbot):
    editor = ActionEditor(registry())
    qtbot.addWidget(editor)
    editor.config_form.editor("keywords").setText("等待")

    editor.add_button.click()

    assert editor.action_specs()[0].capability == "system.wait"
    assert editor.action_specs()[0].config["keywords"] == "等待"


def test_action_editor_preserves_runtime_coordinate_binding(qtbot):
    capabilities = registry()
    capabilities.register_action(Capability("input.mouse", MouseActionConfig))
    editor = ActionEditor(capabilities)
    qtbot.addWidget(editor)
    editor.capability_combo.setCurrentIndex(editor.capability_combo.findData("input.mouse"))
    position = editor.config_form.editor("position")
    assert isinstance(position, TupleFieldEditor)
    position.setBinding("$result.primary.position")

    editor.add_button.click()

    assert editor.error_label.text() == ""
    assert editor.action_specs()[0].config["position"] == "$result.primary.position"


def test_action_editor_loads_and_updates_an_existing_action(qtbot):
    editor = ActionEditor(registry())
    qtbot.addWidget(editor)
    editor.set_actions(
        [
            ActionSpec(
                capability="system.wait",
                config=OcrConditionConfig(keywords="旧值").model_dump(mode="python"),
            )
        ]
    )

    editor.config_form.editor("keywords").setText("新值")
    editor.update_button.click()

    assert len(editor.action_specs()) == 1
    assert editor.action_specs()[0].config["keywords"] == "新值"


def test_route_editor_selects_cross_group_workflow_target(qtbot):
    first = Workflow(name="A1")
    second = Workflow(name="B1")
    project = Project(
        name="p",
        groups=[
            FlowGroup(name="A", workflows=[first]),
            FlowGroup(name="B", workflows=[second]),
        ],
    )
    editor = RouteEditor(project)
    qtbot.addWidget(editor)
    editor.target_combo.setCurrentIndex(editor.target_combo.findData(RouteTargetKind.JUMP_WORKFLOW))
    editor.workflow_combo.setCurrentIndex(editor.workflow_combo.findData(second.id))

    editor.add_button.click()

    assert editor.routes()[0].target == RouteTarget.jump_workflow(second.id)


def test_route_editor_loads_and_updates_an_existing_route(qtbot):
    first = Workflow(name="A")
    second = Workflow(name="B")
    project = Project(
        name="p",
        groups=[FlowGroup(name="g", workflows=[first, second])],
    )
    editor = RouteEditor(project)
    qtbot.addWidget(editor)
    editor.set_routes([RouteRule(outcome=StepOutcome.SUCCESS, target=RouteTarget.end())])
    editor.target_combo.setCurrentIndex(editor.target_combo.findData(RouteTargetKind.JUMP_WORKFLOW))
    editor.workflow_combo.setCurrentIndex(editor.workflow_combo.findData(second.id))

    editor.update_button.click()

    assert len(editor.routes()) == 1
    assert editor.routes()[0].target == RouteTarget.jump_workflow(second.id)


def test_route_editor_selects_next_step_from_current_workflow(qtbot):
    first_step = AutomationStep(name="first")
    second_step = AutomationStep(name="second")
    workflow = Workflow(name="main", steps=[first_step, second_step])
    project = Project(name="p", groups=[FlowGroup(name="g", workflows=[workflow])])
    editor = RouteEditor(project)
    qtbot.addWidget(editor)
    editor.set_step_context(first_step.id)
    editor.target_combo.setCurrentIndex(editor.target_combo.findData(RouteTargetKind.NEXT_STEP))
    editor.step_combo.setCurrentIndex(editor.step_combo.findData(second_step.id))

    editor.add_button.click()

    assert editor.routes()[0].target == RouteTarget.next_step(second_step.id)


def test_route_editor_selects_count_predicate_reference(qtbot):
    first = Workflow(name="A")
    counted_step = AutomationStep(name="counted")
    second = Workflow(name="B", steps=[counted_step])
    project = Project(
        name="p",
        groups=[FlowGroup(name="g", workflows=[first, second])],
    )
    editor = RouteEditor(project)
    qtbot.addWidget(editor)
    editor.target_combo.setCurrentIndex(editor.target_combo.findData(RouteTargetKind.END))
    editor.predicate_source_combo.setCurrentIndex(
        editor.predicate_source_combo.findData("step_count")
    )
    editor.predicate_step_combo.setCurrentIndex(
        editor.predicate_step_combo.findData(counted_step.id)
    )
    editor.predicate_expected_edit.setText("3")

    editor.add_button.click()

    assert editor.routes()[0].predicate == RoutePredicate.step_count(
        counted_step.id,
        ComparisonOperator.EQ,
        3,
    )


def test_route_editor_limits_count_predicates_to_numeric_operators(qtbot):
    editor = RouteEditor()
    qtbot.addWidget(editor)
    editor.predicate_source_combo.setCurrentIndex(
        editor.predicate_source_combo.findData("workflow_count")
    )

    operators = {
        editor.predicate_operator_combo.itemData(index)
        for index in range(editor.predicate_operator_combo.count())
    }

    assert ComparisonOperator.CONTAINS not in operators
    assert ComparisonOperator.MATCHES not in operators
    assert ComparisonOperator.GE in operators


def test_route_editor_adds_variable_predicate(qtbot):
    editor = RouteEditor()
    qtbot.addWidget(editor)
    editor.target_combo.setCurrentIndex(editor.target_combo.findData(RouteTargetKind.END))
    editor.predicate_source_combo.setCurrentIndex(
        editor.predicate_source_combo.findData("task_variable")
    )
    editor.predicate_key_edit.setText("battle_ready")
    editor.predicate_operator_combo.setCurrentIndex(
        editor.predicate_operator_combo.findData(ComparisonOperator.EQ)
    )
    editor.predicate_expected_edit.setText("true")

    editor.add_button.click()

    assert editor.routes()[0].predicate == RoutePredicate.task_variable(
        "battle_ready", ComparisonOperator.EQ, True
    )


def test_property_panel_applies_guided_action_editor_changes(qtbot):
    panel = PropertyPanel(registry(), Project(name="p"))
    qtbot.addWidget(panel)
    panel.set_step(AutomationStep(name="step"))
    panel.action_editor.config_form.editor("keywords").setText("等待")
    panel.action_editor.add_button.click()

    with qtbot.waitSignal(panel.stepChanged) as blocker:
        panel.apply_button.click()

    assert blocker.args[0].actions[0].capability == "system.wait"
    assert blocker.args[0].actions[0].config["keywords"] == "等待"


def test_condition_editor_switches_leaf_capability_and_preserves_region(qtbot, tmp_path):
    editor = ConditionEditor(registry())
    qtbot.addWidget(editor)
    editor.set_condition(
        LeafCondition(
            id="screen",
            capability="vision.ocr",
            config=OcrConditionConfig(keywords="开始", region=(1, 2, 30, 40)).model_dump(
                mode="python"
            ),
        )
    )
    editor.capability_combo.setCurrentIndex(editor.capability_combo.findData("vision.image"))
    editor.config_form.editor("template_path").setText(str(tmp_path / "target.png"))

    condition = editor.condition()

    assert condition.capability == "vision.image"
    assert condition.config["region"] == (1, 2, 30, 40)

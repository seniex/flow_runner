import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QEvent, QObject
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from flow_runner.capabilities.actions.keyboard import KeyboardActionConfig
from flow_runner.capabilities.actions.mouse import MouseActionConfig
from flow_runner.capabilities.actions.process import LaunchProcessConfig
from flow_runner.capabilities.actions.wait import WaitActionConfig
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
from flow_runner.ui.layouts import CompactFlowLayout
from flow_runner.ui.localization import action_summary
from flow_runner.ui.panels.property_panel import PropertyPanel
from flow_runner.ui.region_capture import PointCapture, TemplateCapture


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


def _action_capability_button(editor: ActionEditor, capability: str) -> QPushButton:
    return next(
        button
        for button in editor.capability_buttons.buttons()
        if button.property("capability") == capability
    )


class _ShownTopLevelRecorder(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.widgets = []

    def eventFilter(self, watched, event):  # noqa: N802
        if event.type() == QEvent.Type.Show and isinstance(watched, QWidget) and watched.isWindow():
            self.widgets.append(watched)
        return False


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
                "scale": 1.0,
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
    assert dialog.control_workflow_combo.itemText(0) == "01. 组 / 01. 当前流程"
    assert dialog.control_step_combo.itemText(0) == "01. 目标步骤"
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


def test_path_field_editor_emits_selected_file_and_uses_configured_filter(qtbot, monkeypatch):
    selected = Path("C:/tools/task.py")
    calls = []
    monkeypatch.setattr(
        "flow_runner.ui.editors.model_form.QFileDialog.getOpenFileName",
        lambda parent, title, current, file_filter: (
            calls.append((parent, title, current, file_filter)) or (str(selected), file_filter)
        ),
    )
    editor = PathFieldEditor(file_filter="程序和脚本 (*.exe *.py)")
    qtbot.addWidget(editor)
    selected_spy = QSignalSpy(editor.fileSelected)

    editor.browse_button.click()

    assert editor.text() == str(selected)
    assert selected_spy.count() == 1
    assert selected_spy.at(0) == [str(selected)]
    assert calls[0][1:] == ("选择文件", "", "程序和脚本 (*.exe *.py)")


def test_launch_form_replaces_inferred_script_prefix_and_automatic_directory(qtbot, tmp_path):
    old_script = tmp_path / "old" / "old.py"
    new_script = tmp_path / "new" / "任务.py"
    old_script.parent.mkdir()
    new_script.parent.mkdir()
    form = ModelForm(LaunchProcessConfig)
    qtbot.addWidget(form)
    form.set_values(
        {
            "path": Path(sys.executable),
            "arguments": [str(old_script), "--profile", "daily"],
            "working_directory": old_script.parent,
        }
    )
    changed_spy = QSignalSpy(form.changed)

    path_editor = form.editor("path")
    assert isinstance(path_editor, PathFieldEditor)
    path_editor.fileSelected.emit(str(new_script))

    values = form.values()
    assert values["path"] == str(Path(sys.executable).resolve())
    assert values["arguments"] == [str(new_script.resolve()), "--profile", "daily"]
    assert values["working_directory"] == str(new_script.parent.resolve())
    assert changed_spy.count() == 1


def test_launch_form_preserves_custom_working_directory(qtbot, tmp_path):
    old_script = tmp_path / "old.py"
    new_script = tmp_path / "new.py"
    custom_directory = tmp_path / "custom"
    form = ModelForm(LaunchProcessConfig)
    qtbot.addWidget(form)
    form.set_values(
        {
            "path": Path(sys.executable),
            "arguments": [str(old_script), "--safe"],
            "working_directory": custom_directory,
        }
    )

    path_editor = form.editor("path")
    assert isinstance(path_editor, PathFieldEditor)
    path_editor.fileSelected.emit(str(new_script))

    assert form.values()["working_directory"] == str(custom_directory)


def test_action_summaries_show_target_file_names():
    python_action = ActionSpec(
        capability="system.launch",
        config={"path": Path(sys.executable), "arguments": ["C:/jobs/任务.py"]},
    )
    batch_action = ActionSpec(
        capability="system.launch",
        config={"path": "C:/Windows/System32/cmd.exe", "arguments": ["/c", "C:/jobs/启动.bat"]},
    )
    executable_action = ActionSpec(
        capability="system.launch",
        config={"path": "C:/tools/程序.exe", "arguments": []},
    )
    playback_action = ActionSpec(
        capability="recording.playback",
        config={"path": "C:/recordings/latest.json"},
    )

    assert action_summary(python_action) == "启动程序：任务.py"
    assert action_summary(batch_action) == "启动程序：启动.bat"
    assert action_summary(executable_action) == "启动程序：程序.exe"
    assert action_summary(playback_action) == "播放录制：latest.json"


def test_property_panel_routes_region_and_template_capture_to_condition_form(qtbot, tmp_path):
    class CaptureService:
        def __init__(self):
            self.pick_targets = []
            self.template_targets = []

        def pick_region(self, target, parent=None):
            self.pick_targets.append((target, parent))
            return (10, 20, 110, 120)

        def capture_template(self, target, parent=None):
            self.template_targets.append((target, parent))
            return TemplateCapture(
                region=(30, 40, 130, 140),
                path=tmp_path / "templates" / "target.png",
            )

    service = CaptureService()
    panel = PropertyPanel(
        registry(),
        Project(name="p"),
        region_capture=service,
    )
    qtbot.addWidget(panel)
    panel.set_step(
        AutomationStep(
            name="OCR",
            condition=LeafCondition(
                id="ocr",
                capability="vision.ocr",
                config={"target": "window:Game", "keywords": "开始"},
            ),
        )
    )

    panel.condition_editor.config_form.editor("region").pick_button.click()
    assert panel.condition_editor.config_form.values()["region"] == (10, 20, 110, 120)
    assert service.pick_targets[0][0] == "window:Game"

    panel.set_step(
        AutomationStep(
            name="图片",
            condition=LeafCondition(
                id="image",
                capability="vision.image",
                config={"target": "desktop", "template_path": "old.png"},
            ),
        )
    )
    panel.condition_editor.config_form.editor("template_path").capture_button.click()

    values = panel.condition_editor.config_form.values()
    assert values["region"] == (30, 40, 130, 140)
    assert values["template_path"] == str(tmp_path / "templates" / "target.png")
    assert service.template_targets[0][0] == "desktop"


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


def test_policy_editor_summarizes_core_policy_and_hides_advanced_rows(qtbot):
    editor = PolicyEditor(registry())
    qtbot.addWidget(editor)
    editor.set_policies(
        ConditionPolicy(
            mode=ConditionMode.UNTIL,
            interval_seconds=1.0,
            max_attempts=31,
            timeout_seconds=60.0,
        ),
        ActionPolicy(max_attempts=1, retry_interval_seconds=2.0),
    )

    assert editor.summary_label.text() == ("持续检测：每 1 秒一次，最多 31 次\n动作失败：不重试")
    assert editor.timeout_spin.isHidden()
    assert editor.action_retry_spin.isHidden()
    assert editor.before_actions_editor.isHidden()
    assert editor.after_no_match_actions_editor.isHidden()

    editor.set_advanced_visible(True)

    assert not editor.timeout_spin.isHidden()
    assert not editor.action_retry_spin.isHidden()
    assert not editor.before_actions_editor.isHidden()
    assert not editor.after_no_match_actions_editor.isHidden()


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
    assert _action_capability_button(actions, "system.wait").text() == "等待"
    assert routes.routes() == [route]


def test_action_editor_uses_wrapping_capability_buttons(qtbot):
    editor = ActionEditor(registry())
    qtbot.addWidget(editor)

    assert not hasattr(editor, "capability_combo")
    assert isinstance(editor.capability_layout, CompactFlowLayout)
    assert {button.property("capability") for button in editor.capability_buttons.buttons()} == {
        metadata.name for metadata in registry().action_metadata()
    }


def test_action_capability_button_switches_form_and_is_exclusive(qtbot):
    capabilities = registry()
    capabilities.register_action(Capability("input.mouse", MouseActionConfig))
    editor = ActionEditor(capabilities)
    qtbot.addWidget(editor)
    wait_button = _action_capability_button(editor, "system.wait")
    mouse_button = _action_capability_button(editor, "input.mouse")

    mouse_button.click()

    assert mouse_button.isChecked()
    assert not wait_button.isChecked()
    assert editor.current_capability() == "input.mouse"
    assert editor.config_form.editor("operation") is not None


def test_dynamic_guided_forms_do_not_show_parentless_buttons(qtbot):
    capabilities = registry()
    capabilities.register_action(Capability("input.mouse", MouseActionConfig))
    panel = PropertyPanel(capabilities, Project(name="p"))
    qtbot.addWidget(panel)
    panel.show()
    recorder = _ShownTopLevelRecorder()
    QApplication.instance().installEventFilter(recorder)
    try:
        _action_capability_button(panel.action_editor, "input.mouse").click()
        panel.set_step(
            AutomationStep(
                name="image and mouse",
                condition=LeafCondition(
                    id="image",
                    capability="vision.image",
                    config={"template_path": "template.png"},
                ),
                actions=[ActionSpec(capability="input.mouse", config={})],
            )
        )
        qtbot.wait(1)
    finally:
        QApplication.instance().removeEventFilter(recorder)

    assert [widget.objectName() for widget in recorder.widgets] == []


def test_property_panel_has_no_horizontal_scroll_for_image_and_mouse_forms(qtbot):
    capabilities = registry()
    capabilities.register_action(Capability("input.mouse", MouseActionConfig))
    panel = PropertyPanel(capabilities, Project(name="p"))
    qtbot.addWidget(panel)
    panel.resize(1000, 800)
    panel.set_step(
        AutomationStep(
            name="image and mouse",
            condition=LeafCondition(
                id="image",
                capability="vision.image",
                config={"template_path": "template.png"},
            ),
            actions=[ActionSpec(capability="input.mouse", config={})],
        )
    )
    panel.show()
    qtbot.wait(1)

    assert panel.horizontalScrollBar().maximum() == 0


def test_action_editor_selects_button_when_loading_existing_action(qtbot):
    editor = ActionEditor(registry())
    qtbot.addWidget(editor)
    editor.set_actions([ActionSpec(capability="system.wait", config={"keywords": "等待"})])

    assert _action_capability_button(editor, "system.wait").isChecked()
    assert editor.config_form.editor("keywords").text() == "等待"


def test_action_editor_adds_action_from_generated_config_form(qtbot):
    editor = ActionEditor(registry())
    qtbot.addWidget(editor)
    editor.config_form.editor("keywords").setText("等待")

    editor.add_button.click()

    assert editor.action_specs()[0].capability == "system.wait"
    assert editor.action_specs()[0].config["keywords"] == "等待"


def test_pending_unadded_action_or_route_requires_explicit_add(qtbot):
    actions = ActionEditor(registry())
    routes = RouteEditor()
    qtbot.addWidget(actions)
    qtbot.addWidget(routes)

    actions.config_form.editor("keywords").setText("draft")
    routes.target_combo.setCurrentIndex(routes.target_combo.findData(RouteTargetKind.END))

    with pytest.raises(ValueError, match="请先添加当前动作"):
        actions.commit_pending()
    with pytest.raises(ValueError, match="请先添加当前路由"):
        routes.commit_pending()


def test_action_editor_preserves_runtime_coordinate_binding(qtbot):
    capabilities = registry()
    capabilities.register_action(Capability("input.mouse", MouseActionConfig))
    editor = ActionEditor(capabilities)
    qtbot.addWidget(editor)
    _action_capability_button(editor, "input.mouse").click()
    position = editor.config_form.editor("position")
    assert isinstance(position, TupleFieldEditor)
    position.setBinding("$result.primary.position")

    editor.add_button.click()

    assert editor.error_label.text() == ""
    assert editor.action_specs()[0].config["position"] == "$result.primary.position"


def test_mouse_form_point_picker_uses_its_target_and_sets_coordinate_space(qtbot):
    calls = []

    def pick_point(target):
        calls.append(target)
        return PointCapture(position=(25, 40), coordinate_space="target")

    form = ModelForm(MouseActionConfig, pick_point=pick_point)
    qtbot.addWidget(form)
    form.editor("target").setText("window:Game")
    position = form.editor("position")
    position.point_button.click()

    assert calls == ["window:Game"]
    assert form.values()["position"] == (25, 40)
    assert form.values()["coordinate_space"] == "target"


def test_mouse_point_cancel_preserves_existing_values(qtbot):
    form = ModelForm(MouseActionConfig, pick_point=lambda target: None)
    qtbot.addWidget(form)
    form.set_values(
        {
            "target": "window:Game",
            "coordinate_space": "target",
            "position": (8, 9),
        }
    )
    form.editor("position").point_button.click()
    assert form.values()["position"] == (8, 9)
    assert form.values()["coordinate_space"] == "target"


def test_switching_mouse_position_to_binding_forces_screen_space(qtbot):
    form = ModelForm(MouseActionConfig)
    qtbot.addWidget(form)
    form.set_values(
        {
            "target": "window:Game",
            "coordinate_space": "target",
            "position": (8, 9),
        }
    )
    form.editor("position").setBinding("$result.primary.position")
    assert form.values()["coordinate_space"] == "screen"


def test_point_button_is_visible_only_for_mouse_position(qtbot):
    mouse_form = ModelForm(MouseActionConfig, pick_point=lambda target: None)
    region_form = ModelForm(ImageConditionConfig, pick_region=lambda target: (1, 2, 3, 4))
    qtbot.addWidget(mouse_form)
    qtbot.addWidget(region_form)

    assert not mouse_form.editor("position").point_button.isHidden()
    assert mouse_form.editor("offset").point_button.isHidden()
    assert not region_form.editor("region").pick_button.isHidden()
    assert region_form.editor("region").point_button.isHidden()


def test_action_editor_serializes_picked_window_point(qtbot):
    capabilities = CapabilityRegistry()
    capabilities.register_action(Capability("input.mouse", MouseActionConfig))
    editor = ActionEditor(
        capabilities,
        pick_point=lambda target: PointCapture((25, 40), "target"),
    )
    qtbot.addWidget(editor)
    target = editor.config_form.editor("target")
    target.setText("window:Game")
    editor.config_form.editor("position").point_button.click()
    editor.add_button.click()

    assert editor.action_specs()[0].config == {
        "operation": "click",
        "position": (25, 40),
        "offset": (0, 0),
        "button": "left",
        "clicks": 1,
        "interval": 0.0,
        "duration": 0.0,
        "scroll_units": 1,
        "jitter_pixels": 0,
        "settle_delay": 0.0,
        "target": "window:Game",
        "coordinate_space": "target",
    }


def test_policy_action_editors_support_mouse_point_picker(qtbot):
    capabilities = CapabilityRegistry()
    capabilities.register_action(Capability("input.mouse", MouseActionConfig))
    calls = []

    def pick_point(target):
        calls.append(target)
        return PointCapture((15, 30), "target")

    editor = PolicyEditor(
        capabilities,
        show_advanced=True,
        pick_point=pick_point,
    )
    qtbot.addWidget(editor)

    for actions in (
        editor.before_actions_editor,
        editor.after_no_match_actions_editor,
    ):
        actions.config_form.editor("target").setText("window:Game")
        actions.config_form.editor("position").point_button.click()
        assert actions.config_form.values()["position"] == (15, 30)
        assert actions.config_form.values()["coordinate_space"] == "target"

    assert calls == ["window:Game", "window:Game"]


def test_guided_add_mouse_form_uses_point_capture_service(qtbot):
    capabilities = CapabilityRegistry()
    capabilities.register_action(Capability("input.mouse", MouseActionConfig))
    calls = []

    class PointService:
        def pick_point(self, target, parent):
            calls.append((target, parent))
            return PointCapture((25, 40), "target")

    dialog = GuidedAddDialog(capabilities, point_capture=PointService())
    qtbot.addWidget(dialog)
    dialog.category_combo.setCurrentText("执行")
    dialog.config_form.editor("target").setText("window:Game")
    dialog.config_form.editor("position").point_button.click()

    assert calls == [("window:Game", dialog)]
    assert dialog.config_form.values()["position"] == (25, 40)
    assert dialog.config_form.values()["coordinate_space"] == "target"


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


def test_action_editor_commits_pending_form_before_switching_or_copying(qtbot):
    editor = ActionEditor(registry())
    qtbot.addWidget(editor)
    editor.set_actions(
        [
            ActionSpec(capability="system.wait", config={"keywords": "first"}),
            ActionSpec(capability="system.wait", config={"keywords": "second"}),
        ]
    )

    editor.config_form.editor("keywords").setText("switched")
    editor.action_list.setCurrentRow(1)
    assert editor.action_specs()[0].config["keywords"] == "switched"

    editor.config_form.editor("keywords").setText("copied")
    editor.copy_button.click()
    assert [action.config["keywords"] for action in editor.action_specs()] == [
        "switched",
        "copied",
        "copied",
    ]


def test_action_editor_localizes_and_summarizes_mixed_action_sequence(qtbot):
    capabilities = CapabilityRegistry()
    capabilities.register_action(Capability("input.mouse", MouseActionConfig))
    capabilities.register_action(Capability("input.keyboard", KeyboardActionConfig))
    capabilities.register_action(Capability("system.wait", WaitActionConfig))
    editor = ActionEditor(capabilities)
    qtbot.addWidget(editor)
    editor.set_actions(
        [
            ActionSpec(
                capability="input.mouse",
                config={"operation": "click", "position": [100, 200]},
            ),
            ActionSpec(
                capability="input.keyboard",
                config={"operation": "press", "key": "q"},
            ),
            ActionSpec(capability="system.wait", config={"seconds": 0.5}),
        ]
    )

    labels = [editor.action_list.item(index).text() for index in range(3)]

    assert _action_capability_button(editor, "input.mouse").text() == "鼠标操作"
    assert labels == [
        "1. 鼠标：左键点击 (100, 200)",
        "2. 键盘：按下并释放 q",
        "3. 等待：0.5 秒",
    ]


def test_action_editor_copies_selected_action(qtbot):
    editor = ActionEditor(registry())
    qtbot.addWidget(editor)
    action = ActionSpec(capability="system.wait", config={"keywords": "保留"})
    editor.set_actions([action])

    editor.copy_button.click()

    assert editor.action_specs() == [action, action]


def test_model_form_uses_chinese_field_and_choice_labels(qtbot):
    form = ModelForm(MouseActionConfig)
    qtbot.addWidget(form)
    operation = form.editor("operation")
    settle_delay = form.editor("settle_delay")

    assert form.layout().labelForField(settle_delay).text() == "点击前稳定等待（秒）"
    assert operation.itemText(operation.findData("click")) == "点击"


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
    editor.workflow_combo.setCurrentIndex(editor.workflow_combo.findData(str(second.id)))

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
    editor.workflow_combo.setCurrentIndex(editor.workflow_combo.findData(str(second.id)))

    editor.update_button.click()

    assert len(editor.routes()) == 1
    assert editor.routes()[0].target == RouteTarget.jump_workflow(second.id)


def test_route_editor_commits_pending_form_before_switching_or_reordering(qtbot):
    first = Workflow(name="A")
    second = Workflow(name="B")
    project = Project(name="p", groups=[FlowGroup(name="g", workflows=[first, second])])
    editor = RouteEditor(project)
    qtbot.addWidget(editor)
    original_second = RouteRule(outcome=StepOutcome.FAILURE, target=RouteTarget.end())
    editor.set_routes(
        [
            RouteRule(outcome=StepOutcome.SUCCESS, target=RouteTarget.end()),
            original_second,
        ]
    )

    editor.target_combo.setCurrentIndex(editor.target_combo.findData(RouteTargetKind.JUMP_WORKFLOW))
    editor.workflow_combo.setCurrentIndex(editor.workflow_combo.findData(str(second.id)))
    editor.route_list.setCurrentRow(1)
    assert editor.routes()[0].target == RouteTarget.jump_workflow(second.id)

    editor.target_combo.setCurrentIndex(editor.target_combo.findData(RouteTargetKind.CALL_WORKFLOW))
    editor.workflow_combo.setCurrentIndex(editor.workflow_combo.findData(str(first.id)))
    editor.up_button.click()
    assert editor.routes() == [
        RouteRule(
            outcome=StepOutcome.FAILURE,
            target=RouteTarget.call_workflow(first.id),
        ),
        RouteRule(
            outcome=StepOutcome.SUCCESS,
            target=RouteTarget.jump_workflow(second.id),
        ),
    ]


def test_route_editor_selects_next_step_from_current_workflow(qtbot):
    first_step = AutomationStep(name="first")
    second_step = AutomationStep(name="second")
    workflow = Workflow(name="main", steps=[first_step, second_step])
    project = Project(name="p", groups=[FlowGroup(name="g", workflows=[workflow])])
    editor = RouteEditor(project)
    qtbot.addWidget(editor)
    editor.set_step_context(first_step.id)
    editor.target_combo.setCurrentIndex(editor.target_combo.findData(RouteTargetKind.NEXT_STEP))
    editor.step_combo.setCurrentIndex(editor.step_combo.findData(str(second_step.id)))

    editor.add_button.click()

    assert editor.routes()[0].target == RouteTarget.next_step(second_step.id)


def test_route_editor_labels_and_exposes_editable_same_workflow_step_target(qtbot):
    first_step = AutomationStep(name="first")
    second_step = AutomationStep(name="second")
    third_step = AutomationStep(name="third")
    workflow = Workflow(name="main", steps=[first_step, second_step, third_step])
    project = Project(name="p", groups=[FlowGroup(name="g", workflows=[workflow])])
    editor = RouteEditor(project)
    qtbot.addWidget(editor)
    editor.set_step_context(first_step.id)

    editor.target_combo.setCurrentIndex(editor.target_combo.findData(RouteTargetKind.END))
    editor.target_combo.setCurrentIndex(editor.target_combo.findData(RouteTargetKind.NEXT_STEP))

    target_index = editor.target_combo.findData(RouteTargetKind.NEXT_STEP)
    assert editor.target_combo.itemText(target_index) == "跳到本流程中的指定步骤"
    assert not editor.step_combo.isHidden()
    assert editor.step_combo.isEnabled()

    editor.step_combo.setCurrentIndex(editor.step_combo.findData(str(third_step.id)))
    editor.add_button.click()

    assert editor.routes()[0].target == RouteTarget.next_step(third_step.id)


def test_route_editor_defaults_to_ordered_next_step_and_leaves_last_step_unselected(qtbot):
    first_step = AutomationStep(name="first")
    second_step = AutomationStep(name="second")
    third_step = AutomationStep(name="third")
    workflow = Workflow(name="main", steps=[first_step, second_step, third_step])
    project = Project(name="p", groups=[FlowGroup(name="g", workflows=[workflow])])
    editor = RouteEditor(project)
    qtbot.addWidget(editor)

    editor.set_step_context(first_step.id)

    assert editor.step_combo.currentData() == str(second_step.id)

    editor.set_step_context(third_step.id)

    assert editor.step_combo.currentIndex() == -1
    assert [editor.step_combo.itemData(index) for index in range(editor.step_combo.count())] == [
        str(first_step.id),
        str(second_step.id),
        str(third_step.id),
    ]


def test_route_editor_uses_reordered_sequence_for_default_but_preserves_existing_uuid_target(qtbot):
    first_step = AutomationStep(name="first")
    second_step = AutomationStep(name="second")
    third_step = AutomationStep(name="third")
    workflow = Workflow(name="main", steps=[first_step, third_step, second_step])
    project = Project(name="p", groups=[FlowGroup(name="g", workflows=[workflow])])
    editor = RouteEditor(project)
    qtbot.addWidget(editor)

    editor.set_step_context(first_step.id)

    assert editor.step_combo.currentData() == str(third_step.id)

    existing_route = RouteRule(
        outcome=StepOutcome.SUCCESS,
        target=RouteTarget.next_step(second_step.id),
    )
    editor.set_routes([existing_route])

    assert editor.step_combo.currentData() == str(second_step.id)
    editor.commit_current()
    assert editor.routes() == [existing_route]

    moved_again = Workflow(
        id=workflow.id,
        name=workflow.name,
        steps=[second_step, first_step, third_step],
    )
    editor.set_project(Project(name="p", groups=[FlowGroup(name="g", workflows=[moved_again])]))

    assert editor.step_combo.currentData() == str(second_step.id)
    editor.commit_current()
    assert editor.routes() == [existing_route]


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
        editor.predicate_step_combo.findData(str(counted_step.id))
    )
    editor.predicate_expected_edit.setText("3")

    editor.add_button.click()

    assert editor.routes()[0].predicate == RoutePredicate.step_count(
        counted_step.id,
        ComparisonOperator.EQ,
        3,
    )


def test_route_editor_round_trips_independently_loaded_uuid_targets(qtbot):
    next_step = AutomationStep(name="next")
    target = Workflow(name="B")
    current_step = AutomationStep(
        name="current",
        routes=[
            RouteRule(
                outcome=StepOutcome.SUCCESS,
                target=RouteTarget.jump_workflow(target.id),
            ),
            RouteRule(
                outcome=StepOutcome.FAILURE,
                target=RouteTarget.call_workflow(target.id),
            ),
            RouteRule(
                outcome=StepOutcome.TIMEOUT,
                target=RouteTarget.next_step(next_step.id),
            ),
        ],
    )
    current = Workflow(name="A", steps=[current_step, next_step])
    loaded = Project.model_validate_json(
        Project(
            name="p",
            groups=[FlowGroup(name="g", workflows=[current, target])],
        ).model_dump_json()
    )
    loaded_current = loaded.groups[0].workflows[0]
    loaded_step = loaded_current.steps[0]
    editor = RouteEditor(loaded)
    qtbot.addWidget(editor)
    editor.set_step_context(loaded_step.id)

    for route in loaded_step.routes:
        editor.set_routes([route])
        editor.commit_current()
        assert editor.routes() == [route]


def test_route_editor_round_trips_independently_loaded_count_references(qtbot):
    counted_step = AutomationStep(name="counted")
    counted = Workflow(name="B", steps=[counted_step])
    current_step = AutomationStep(
        name="current",
        routes=[
            RouteRule(
                outcome=StepOutcome.SUCCESS,
                target=RouteTarget.end(),
                predicate=RoutePredicate.workflow_count(
                    counted.id,
                    ComparisonOperator.GE,
                    2,
                ),
            ),
            RouteRule(
                outcome=StepOutcome.FAILURE,
                target=RouteTarget.end(),
                predicate=RoutePredicate.step_count(
                    counted_step.id,
                    ComparisonOperator.EQ,
                    3,
                ),
            ),
        ],
    )
    current = Workflow(name="A", steps=[current_step])
    loaded = Project.model_validate_json(
        Project(
            name="p",
            groups=[FlowGroup(name="g", workflows=[current, counted])],
        ).model_dump_json()
    )
    loaded_step = loaded.groups[0].workflows[0].steps[0]
    editor = RouteEditor(loaded)
    qtbot.addWidget(editor)
    editor.set_step_context(loaded_step.id)

    for route in loaded_step.routes:
        editor.set_routes([route])
        editor.commit_current()
        assert editor.routes() == [route]


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


def test_route_editor_adds_result_binding_predicate(qtbot):
    editor = RouteEditor()
    qtbot.addWidget(editor)
    editor.target_combo.setCurrentIndex(editor.target_combo.findData(RouteTargetKind.END))
    editor.predicate_source_combo.setCurrentIndex(editor.predicate_source_combo.findData("binding"))
    editor.predicate_binding_editor.setValue('$result.children["ocr_a"].text')
    editor.predicate_expected_edit.setText('"ready"')

    editor.add_button.click()

    assert editor.routes()[0].predicate == RoutePredicate.binding(
        '$result.children["ocr_a"].text',
        ComparisonOperator.EQ,
        "ready",
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


def test_property_panel_commits_pending_policy_action_without_update_click(qtbot):
    before = ActionSpec(capability="system.wait", config={"keywords": "旧值"})
    panel = PropertyPanel(registry(), Project(name="p"))
    qtbot.addWidget(panel)
    panel.set_step(
        AutomationStep(
            name="step",
            condition_policy=ConditionPolicy(before_attempt_actions=[before]),
        )
    )
    panel.policy_editor.before_actions_editor.config_form.editor("keywords").setText("新值")

    step = panel.apply_pending()

    assert step is not None
    assert step.condition_policy.before_attempt_actions[0].config["keywords"] == "新值"


def test_property_panel_does_not_rebuild_untouched_guided_subeditors(qtbot, monkeypatch):
    action = ActionSpec(capability="system.wait", config={"keywords": "动作"})
    policy_action = ActionSpec(capability="system.wait", config={"keywords": "策略"})
    route = RouteRule(outcome=StepOutcome.SUCCESS, target=RouteTarget.end())
    panel = PropertyPanel(registry(), Project(name="p"))
    qtbot.addWidget(panel)
    panel.set_step(
        AutomationStep(
            name="old",
            actions=[action],
            condition_policy=ConditionPolicy(before_attempt_actions=[policy_action]),
            routes=[route],
        )
    )

    monkeypatch.setattr(
        panel.action_editor,
        "_build_current_action",
        lambda: pytest.fail("untouched action editor was rebuilt"),
    )
    monkeypatch.setattr(
        panel.policy_editor.before_actions_editor,
        "_build_current_action",
        lambda: pytest.fail("untouched policy action editor was rebuilt"),
    )
    monkeypatch.setattr(
        panel.route_editor,
        "_current_route",
        lambda: pytest.fail("untouched route editor was rebuilt"),
    )
    panel.name_edit.setText("new")

    updated = panel.apply_pending()

    assert updated is not None
    assert updated.name == "new"
    assert updated.actions == [action]
    assert updated.condition_policy.before_attempt_actions == [policy_action]
    assert updated.routes == [route]


def test_condition_editor_switches_leaf_capability_and_preserves_region(qtbot, tmp_path):
    discarded_fields = []
    editor = ConditionEditor(
        registry(),
        confirm_discard=lambda fields: discarded_fields.append(fields) or True,
    )
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
    assert discarded_fields == [("keywords", "language", "preprocessing", "scale")]


def test_condition_editor_can_cancel_capability_switch_that_discards_fields(qtbot):
    discarded_fields = []
    editor = ConditionEditor(
        registry(),
        confirm_discard=lambda fields: discarded_fields.append(fields) or False,
    )
    qtbot.addWidget(editor)
    editor.set_condition(
        LeafCondition(
            id="screen",
            capability="vision.ocr",
            config=OcrConditionConfig(keywords="开始").model_dump(mode="python"),
        )
    )

    editor.capability_combo.setCurrentIndex(editor.capability_combo.findData("vision.image"))

    assert editor.capability_combo.currentData() == "vision.ocr"
    assert editor.config_form.model_type is OcrConditionConfig
    assert discarded_fields == [("keywords", "language", "preprocessing", "scale")]


def test_route_editor_summaries_use_predicates_and_project_names(qtbot):
    current = AutomationStep(name="开始检测")
    counted = AutomationStep(name="键盘命令")
    primary = Workflow(name="开始游戏", steps=[current, counted])
    alternate = Workflow(name="开始游戏")
    project = Project(
        name="p",
        groups=[
            FlowGroup(name="不思议挂机", workflows=[primary]),
            FlowGroup(name="不思议挂机B", workflows=[alternate]),
        ],
    )
    editor = RouteEditor(project)
    qtbot.addWidget(editor)
    assert editor.workflow_combo.itemText(0) == "01. 不思议挂机 / 01. 开始游戏"
    assert editor.predicate_step_combo.itemText(1).endswith("/ 02. 键盘命令")
    editor.set_step_context(current.id)
    editor.set_routes(
        [
            RouteRule(
                outcome=StepOutcome.TIMEOUT,
                target=RouteTarget.next_step(counted.id),
            ),
            RouteRule(
                outcome=StepOutcome.SUCCESS,
                predicate=RoutePredicate.step_count(
                    counted.id,
                    ComparisonOperator.GT,
                    1,
                ),
                target=RouteTarget.jump_workflow(alternate.id),
            ),
            RouteRule(
                outcome=StepOutcome.SUCCESS,
                target=RouteTarget.jump_workflow(primary.id),
            ),
        ]
    )

    assert [editor.route_list.item(index).text() for index in range(3)] == [
        "超时 → 下一步骤：01. 不思议挂机 / 01. 开始游戏 / 02. 键盘命令",
        "成功 且 01. 不思议挂机 / 01. 开始游戏 / 02. 键盘命令执行次数 > 1 → "
        "跳转流程：02. 不思议挂机B / 01. 开始游戏",
        "成功（否则） → 跳转流程：01. 不思议挂机 / 01. 开始游戏 / 01. 开始检测",
    ]


def test_route_editor_rejects_conditional_route_shadowed_by_unconditional_route(qtbot):
    step = AutomationStep(name="步骤")
    workflow = Workflow(name="流程", steps=[step])
    project = Project(name="p", groups=[FlowGroup(name="组", workflows=[workflow])])
    editor = RouteEditor(project)
    qtbot.addWidget(editor)
    editor.set_step_context(step.id)
    editor.set_routes(
        [
            RouteRule(outcome=StepOutcome.SUCCESS, target=RouteTarget.end()),
            RouteRule(
                outcome=StepOutcome.SUCCESS,
                predicate=RoutePredicate.task_variable(
                    "ready",
                    ComparisonOperator.EQ,
                    True,
                ),
                target=RouteTarget.end(),
            ),
        ]
    )

    with pytest.raises(ValueError, match="第 2 条路由被第 1 条同结果无条件路由遮挡"):
        editor.commit_pending()

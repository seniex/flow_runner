from flow_runner.capabilities.actions.keyboard import KeyboardActionConfig
from flow_runner.capabilities.actions.window import WindowActionConfig
from flow_runner.capabilities.registry import CapabilityRegistry
from flow_runner.domain.project import FlowGroup, Project, Workflow
from flow_runner.domain.routing import RouteTargetKind
from flow_runner.ui.editor_metadata import common_fields_for
from flow_runner.ui.editors.condition_editor import ConditionEditor
from flow_runner.ui.editors.model_form import ModelForm
from flow_runner.ui.editors.policy_editor import PolicyEditor
from flow_runner.ui.editors.route_editor import RouteEditor
from flow_runner.ui.layouts.compact_flow_layout import CompactFlowLayout


def _assert_fields_share_wide_row(layout, *editors):
    layout.parentWidget().resize(1600, 400)
    layout.setGeometry(layout.parentWidget().rect())
    containers = [layout.containerForField(editor) for editor in editors]
    assert all(container is not None for container in containers)
    assert len({container.geometry().top() for container in containers}) == 1


def test_model_form_packs_keyboard_fields_into_compact_rows(qtbot):
    form = ModelForm(KeyboardActionConfig)
    qtbot.addWidget(form)

    assert isinstance(form.form_layout, CompactFlowLayout)
    operation = form.editor("operation")
    key = form.editor("key")
    text = form.editor("text")
    assert form.form_layout.containerForField(operation).property("compactField")
    _assert_fields_share_wide_row(form.form_layout, operation, key, text)


def test_detection_policy_and_route_primary_controls_use_compact_rows(qtbot):
    registry = CapabilityRegistry()
    condition = ConditionEditor(registry)
    policy = PolicyEditor()
    project = Project(name="p", groups=[FlowGroup(name="g", workflows=[Workflow(name="w")])])
    route = RouteEditor(project)
    for widget in (condition, policy, route):
        qtbot.addWidget(widget)

    assert isinstance(condition.control_layout, CompactFlowLayout)
    _assert_fields_share_wide_row(
        condition.control_layout,
        condition.node_id_edit,
        condition.operator_combo,
        condition.capability_combo,
    )
    assert isinstance(policy.compact_layout, CompactFlowLayout)
    _assert_fields_share_wide_row(
        policy.compact_layout,
        policy.mode_combo,
        policy.interval_spin,
        policy.max_attempts_spin,
        policy.action_attempts_spin,
    )
    assert isinstance(route.primary_layout, CompactFlowLayout)
    route.target_combo.setCurrentIndex(route.target_combo.findData(RouteTargetKind.JUMP_WORKFLOW))
    _assert_fields_share_wide_row(
        route.primary_layout,
        route.outcome_combo,
        route.target_combo,
        route.workflow_combo,
    )


def test_window_action_common_fields_stay_on_one_row_and_geometry_switches(qtbot):
    form = ModelForm(
        WindowActionConfig,
        common_fields=common_fields_for("system.window_action"),
    )
    qtbot.addWidget(form)
    form.resize(620, 120)
    form.form_layout.setGeometry(form.rect())

    operation = form.editor("operation")
    process_name = form.editor("process_name")
    fallback_process_names = form.editor("fallback_process_names")
    geometry = form.editor("geometry")
    assert geometry.isHidden()
    assert form.editor("title").isHidden()

    operation.setCurrentIndex(operation.findData("move_resize"))
    form.form_layout.setGeometry(form.rect())
    containers = [
        form.form_layout.containerForField(editor)
        for editor in (operation, process_name, fallback_process_names, geometry)
    ]
    assert not geometry.isHidden()
    assert len({container.geometry().top() for container in containers}) == 1

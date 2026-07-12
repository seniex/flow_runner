from PySide6.QtGui import QCloseEvent

from flow_runner.domain.enums import StepOutcome
from flow_runner.domain.project import (
    AutomationStep,
    FlowGroup,
    ParallelBlock,
    Project,
    Workflow,
)
from flow_runner.domain.results import StepResult
from flow_runner.domain.routing import RouteRule, RouteTarget
from flow_runner.engine.runner import Runner
from flow_runner.ui.main_window import MainWindow
from flow_runner.ui.runner_bridge import RunnerBridge
from flow_runner.ui.view_models.project_view_model import ProjectViewModel


def sample_project():
    workflow = Workflow(
        name="流程1",
        steps=[AutomationStep(name="检测"), AutomationStep(name="点击")],
    )
    return Project(name="挂机", groups=[FlowGroup(name="组A", workflows=[workflow])])


def test_selecting_step_updates_property_panel(qtbot):
    project = sample_project()
    workflow = project.groups[0].workflows[0]
    step = workflow.steps[1]
    window = MainWindow(project)
    qtbot.addWidget(window)

    window.flow_tree.select_workflow(workflow.id)
    window.step_list.select_step(step.id)

    assert window.property_panel.step_id == step.id
    assert window.property_panel.title.text() == "点击"


def test_panels_expose_semantic_object_names(qtbot):
    window = MainWindow(sample_project())
    qtbot.addWidget(window)

    assert window.flow_tree.objectName() == "flowTreePanel"
    assert window.step_list.objectName() == "stepListPanel"
    assert window.property_panel.objectName() == "propertyPanel"


def test_reordering_workflows_does_not_change_route_ids(qtbot):
    second = Workflow(name="二")
    first = Workflow(
        name="一",
        steps=[
            AutomationStep(
                name="跳转",
                routes=[
                    RouteRule(
                        outcome=StepOutcome.SUCCESS,
                        target=RouteTarget.jump_workflow(second.id),
                    )
                ],
            )
        ],
    )
    project = Project(name="p", groups=[FlowGroup(name="g", workflows=[first, second])])
    window = MainWindow(project)
    qtbot.addWidget(window)
    window.flow_tree.select_workflow(second.id)

    window.move_workflow_up_action.trigger()

    assert window.view_model.project.groups[0].workflows[0].id == second.id
    assert window.view_model.project.groups[0].workflows[1].id == first.id
    assert (
        window.view_model.project.groups[0].workflows[1].steps[0].routes[0].target.workflow_id
        == second.id
    )


def test_moving_workflow_across_groups_preserves_uuid_routes(qtbot):
    target = Workflow(name="目标")
    moved = Workflow(
        name="待移动",
        steps=[
            AutomationStep(
                name="跳转",
                routes=[
                    RouteRule(
                        outcome=StepOutcome.SUCCESS,
                        target=RouteTarget.jump_workflow(target.id),
                    )
                ],
            )
        ],
    )
    source_group = FlowGroup(name="A", workflows=[moved])
    target_group = FlowGroup(name="B", workflows=[target])
    project = Project(name="p", groups=[source_group, target_group])
    window = MainWindow(
        project,
        select_group_target=lambda _project, _workflow_id: target_group.id,
    )
    qtbot.addWidget(window)
    window.flow_tree.select_workflow(moved.id)

    window.move_workflow_group_action.trigger()

    assert window.view_model.project.groups[0].workflows == []
    relocated = window.view_model.project.groups[1].workflows[1]
    assert relocated.id == moved.id
    assert relocated.steps[0].routes[0].target.workflow_id == target.id


def test_runtime_toolbar_starts_selected_workflow_and_tracks_completion(qtbot):
    class ImmediateExecutor:
        async def execute(self, step):
            return StepResult(outcome=StepOutcome.SUCCESS)

    project = sample_project()
    workflow = project.groups[0].workflows[0]
    bridge = RunnerBridge(Runner(ImmediateExecutor()))
    window = MainWindow(project, runner_bridge=bridge)
    qtbot.addWidget(window)
    window.flow_tree.select_workflow(workflow.id)

    with qtbot.waitSignal(bridge.finished, timeout=3000):
        window.start_action.trigger()

    assert window.runtime_toolbar.objectName() == "runtimeToolbar"
    assert window.start_action.objectName() == "startWorkflowAction"
    assert window.pause_action.objectName() == "pauseWorkflowAction"
    assert window.stop_action.objectName() == "stopWorkflowAction"
    assert window.run_view_model.state.value == "completed"


def test_runtime_start_without_selection_reports_a_status_message(qtbot):
    project = sample_project()
    window = MainWindow(project, runner_bridge=RunnerBridge(Runner(lambda step: None)))
    qtbot.addWidget(window)

    window.start_action.trigger()

    assert "选择" in window.statusBar().currentMessage()


def test_project_view_model_edits_steps_with_undo_boundary(qtbot):
    project = sample_project()
    workflow = project.groups[0].workflows[0]
    model = ProjectViewModel(project)
    added = AutomationStep(name="新增")

    model.add_step(workflow.id, added)
    model.update_step(workflow.id, added.model_copy(update={"name": "已修改"}))
    model.remove_step(workflow.id, added.id)

    assert not model.dirty
    assert len(model.project.groups[0].workflows[0].steps) == 2
    model.undo()
    assert model.dirty
    assert model.project.groups[0].workflows[0].steps[-1].name == "已修改"


def test_project_view_model_renames_groups_and_workflows(qtbot):
    project = sample_project()
    group = project.groups[0]
    workflow = group.workflows[0]
    model = ProjectViewModel(project)

    model.rename_group(group.id, "新组")
    model.rename_workflow(workflow.id, "新流程")

    assert model.project.groups[0].name == "新组"
    assert model.project.groups[0].workflows[0].name == "新流程"


def test_property_panel_applies_validated_step_edits_to_project(qtbot):
    project = sample_project()
    workflow = project.groups[0].workflows[0]
    step = workflow.steps[0]
    window = MainWindow(project)
    qtbot.addWidget(window)
    window.flow_tree.select_workflow(workflow.id)
    window.step_list.select_step(step.id)

    window.property_panel.name_edit.setText("新检测")
    window.property_panel.enabled_check.setChecked(False)
    window.property_panel.apply_button.click()

    updated = window.view_model.project.groups[0].workflows[0].steps[0]
    assert updated.name == "新检测"
    assert not updated.enabled
    assert window.step_list.list.item(0).text() == "新检测"


def test_dirty_window_can_cancel_close_through_injected_confirmation(qtbot):
    project = sample_project()
    window = MainWindow(project, confirm_close=lambda: "cancel")
    qtbot.addWidget(window)
    window.view_model.rename_group(project.groups[0].id, "changed")
    event = QCloseEvent()

    window.closeEvent(event)

    assert not event.isAccepted()


def test_step_toolbar_adds_moves_removes_and_undoes_steps(qtbot):
    project = sample_project()
    workflow = project.groups[0].workflows[0]
    added = AutomationStep(name="新增")
    window = MainWindow(project, create_step=lambda: added)
    qtbot.addWidget(window)
    window.flow_tree.select_workflow(workflow.id)

    window.add_step_action.trigger()
    window.step_list.select_step(added.id)
    window.move_step_up_action.trigger()

    assert window.view_model.project.groups[0].workflows[0].steps[1].id == added.id

    window.remove_step_action.trigger()
    assert all(
        step.id != added.id for step in window.view_model.project.groups[0].workflows[0].steps
    )

    window.undo_action.trigger()
    assert window.view_model.project.groups[0].workflows[0].steps[1].id == added.id


def test_flow_tree_toolbar_adds_and_renames_groups_and_workflows(qtbot):
    names = iter(["组B", "流程B1", "流程B1新"])
    window = MainWindow(sample_project(), request_name=lambda kind, current="": next(names))
    qtbot.addWidget(window)

    window.add_group_action.trigger()
    new_group = window.view_model.project.groups[-1]
    window.flow_tree.select_group(new_group.id)
    window.add_workflow_action.trigger()
    new_workflow = window.view_model.project.groups[-1].workflows[0]
    window.flow_tree.select_workflow(new_workflow.id)
    window.rename_flow_action.trigger()

    assert window.view_model.project.groups[-1].name == "组B"
    assert window.view_model.project.groups[-1].workflows[0].name == "流程B1新"


def test_settings_action_updates_project_settings_through_view_model(qtbot):
    updated_settings = {
        "ocr_engine": "paddle",
        "paddle_exe_path": "PaddleOCR-json_v1.4.1/PaddleOCR-json.exe",
        "hotkeys": {"start": "F10", "stop": "F11", "pause": "", "record": ""},
    }
    window = MainWindow(sample_project(), edit_settings=lambda current: updated_settings)
    qtbot.addWidget(window)

    window.settings_action.trigger()

    assert window.view_model.project.settings == updated_settings
    assert window.view_model.dirty


def test_selecting_parallel_block_starts_all_configured_workflows(qtbot):
    first = Workflow(name="A", steps=[AutomationStep(name="A1")])
    second = Workflow(name="B", steps=[AutomationStep(name="B1")])
    block = ParallelBlock(name="并行", workflow_ids=[first.id, second.id])
    project = Project(
        name="p",
        groups=[FlowGroup(name="g", workflows=[first, second])],
        parallel_blocks=[block],
    )

    class ImmediateExecutor:
        async def execute(self, step):
            return StepResult(outcome=StepOutcome.SUCCESS)

    bridge = RunnerBridge(Runner(step_executor_factory=lambda token: ImmediateExecutor()))
    window = MainWindow(project, runner_bridge=bridge)
    qtbot.addWidget(window)
    window.flow_tree.select_parallel_block(block.id)

    with qtbot.waitSignal(bridge.finished, timeout=3000) as blocker:
        window.start_action.trigger()

    assert blocker.args[0].block_id == block.id
    assert len(blocker.args[0].workflow_traces) == 2


def test_parallel_block_toolbar_adds_and_deletes_explicit_block(qtbot):
    project = sample_project()
    first = project.groups[0].workflows[0]
    second = Workflow(name="第二流程")
    project = project.model_copy(
        update={
            "groups": [
                FlowGroup(
                    id=project.groups[0].id,
                    name=project.groups[0].name,
                    workflows=[first, second],
                )
            ]
        }
    )
    block = ParallelBlock(name="并行", workflow_ids=[first.id, second.id])
    window = MainWindow(
        project,
        create_parallel_block=lambda: block,
        confirm_delete=lambda label: True,
    )
    qtbot.addWidget(window)

    window.add_parallel_action.trigger()
    window.flow_tree.select_parallel_block(block.id)
    assert window.view_model.project.parallel_blocks == [block]

    window.delete_parallel_action.trigger()
    assert window.view_model.project.parallel_blocks == []


def test_single_step_action_runs_only_selected_step(qtbot):
    project = sample_project()
    workflow = project.groups[0].workflows[0]
    calls = []

    class Executor:
        async def execute(self, step):
            calls.append(step.id)
            return StepResult(outcome=StepOutcome.SUCCESS)

    bridge = RunnerBridge(Runner(step_executor_factory=lambda token: Executor()))
    window = MainWindow(project, runner_bridge=bridge)
    qtbot.addWidget(window)
    window.flow_tree.select_workflow(workflow.id)
    window.step_list.select_step(workflow.steps[1].id)

    with qtbot.waitSignal(bridge.finished, timeout=3000):
        window.run_step_action.trigger()

    assert calls == [workflow.steps[1].id]

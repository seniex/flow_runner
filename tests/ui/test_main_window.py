from PySide6.QtGui import QCloseEvent

from flow_runner.domain.enums import StepOutcome
from flow_runner.domain.project import AutomationStep, FlowGroup, Project, Workflow
from flow_runner.domain.results import StepResult
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
    first = Workflow(name="一")
    second = Workflow(name="二")
    project = Project(name="p", groups=[FlowGroup(name="g", workflows=[first, second])])
    window = MainWindow(project)
    qtbot.addWidget(window)

    window.view_model.move_workflow(second.id, -1)

    assert window.view_model.project.groups[0].workflows[0].id == second.id
    assert window.view_model.project.groups[0].workflows[1].id == first.id


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

from flow_runner.domain.enums import StepOutcome
from flow_runner.domain.project import AutomationStep, FlowGroup, Project, Workflow
from flow_runner.domain.results import StepResult
from flow_runner.engine.runner import Runner
from flow_runner.ui.main_window import MainWindow
from flow_runner.ui.runner_bridge import RunnerBridge


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

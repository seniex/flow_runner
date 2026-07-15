from flow_runner.display_labels import ProjectDisplayIndex
from flow_runner.domain.project import AutomationStep, FlowGroup, Project, Workflow


def test_display_numbers_reset_in_each_direct_container():
    first_steps = [AutomationStep(name="A1"), AutomationStep(name="A2")]
    second_steps = [AutomationStep(name="B1")]
    first_workflows = [
        Workflow(name="流程A", steps=first_steps),
        Workflow(name="流程B", steps=second_steps),
    ]
    second_workflow = Workflow(name="流程C", steps=[AutomationStep(name="C1")])
    project = Project(
        name="p",
        groups=[
            FlowGroup(name="组A", workflows=first_workflows),
            FlowGroup(name="组B", workflows=[second_workflow]),
        ],
    )

    labels = ProjectDisplayIndex(project)

    assert labels.group_label(project.groups[0].id) == "01. 组A"
    assert labels.group_label(project.groups[1].id) == "02. 组B"
    assert labels.workflow_label(first_workflows[1].id) == "02. 流程B"
    assert labels.workflow_label(second_workflow.id) == "01. 流程C"
    assert labels.step_label(first_steps[1].id) == "02. A2"
    assert labels.step_label(second_steps[0].id) == "01. B1"
    assert labels.step_path(first_steps[1].id) == "01. 组A / 01. 流程A / 02. A2"


def test_display_numbers_are_not_written_into_model_names():
    step = AutomationStep(name="原步骤")
    workflow = Workflow(name="原流程", steps=[step])
    group = FlowGroup(name="原组", workflows=[workflow])
    project = Project(name="p", groups=[group])

    ProjectDisplayIndex(project)

    assert group.name == "原组"
    assert workflow.name == "原流程"
    assert step.name == "原步骤"

import importlib

import pytest
from PySide6.QtWidgets import QComboBox

from flow_runner.domain.project import AutomationStep, FlowGroup, Project, Workflow
from flow_runner.ui.main_window import MainWindow


def _project():
    target_step = AutomationStep(name="后续步骤")
    current = Workflow(name="当前流程", steps=[target_step])
    success = Workflow(name="成功流程")
    timeout = Workflow(name="超时流程")
    project = Project(
        name="p",
        groups=[
            FlowGroup(name="主组", workflows=[current]),
            FlowGroup(name="分支组", workflows=[success, timeout]),
        ],
    )
    return project, current, target_step, success, timeout


def _project_with_step(project, workflow_id, step):
    groups = []
    for group in project.groups:
        workflows = [
            workflow.model_copy(update={"steps": [*workflow.steps, step]})
            if workflow.id == workflow_id
            else workflow
            for workflow in group.workflows
        ]
        groups.append(group.model_copy(update={"workflows": workflows}))
    return project.model_copy(update={"groups": groups})


def test_initial_templates_build_valid_ordinary_steps():
    templates = importlib.import_module("flow_runner.ui.step_templates")
    project, current, target_step, success, timeout = _project()
    cases = {
        "ocr_click": {"name": "OCR 点击", "keywords": "开始"},
        "ocr_timeout_continue": {
            "name": "OCR 超时",
            "keywords": "等待",
            "timeout_seconds": 10.0,
            "target_step_id": target_step.id,
        },
        "wait_then_key": {"name": "等待按键", "seconds": 1.5, "key": "space"},
        "activate_window_then_key": {
            "name": "激活按键",
            "window_process_name": "game.exe",
            "key": "f1",
        },
        "jump_after_two_runs": {
            "name": "两轮跳转",
            "target_workflow_id": success.id,
        },
        "success_timeout_branches": {
            "name": "结果分支",
            "success_workflow_id": success.id,
            "timeout_workflow_id": timeout.id,
        },
    }

    assert set(templates.STEP_TEMPLATES) == set(cases)
    for template_id, parameters in cases.items():
        step = templates.build_template_step(
            template_id,
            parameters,
            project=project,
            current_workflow_id=current.id,
        )
        candidate = _project_with_step(project, current.id, step)

        assert isinstance(step, AutomationStep)
        assert candidate.validate_references() == []
        if template_id == "activate_window_then_key":
            assert step.actions[0].config == {
                "operation": "activate",
                "process_name": "game.exe",
            }


def test_template_dialog_uses_project_dropdowns_for_uuid_targets(qtbot):
    dialog_module = importlib.import_module("flow_runner.ui.dialogs.template_step_dialog")
    project, current, _target_step, success, timeout = _project()
    dialog = dialog_module.TemplateStepDialog(project, current_workflow_id=current.id)
    qtbot.addWidget(dialog)

    assert isinstance(dialog.target_step_combo, QComboBox)
    assert isinstance(dialog.target_workflow_combo, QComboBox)
    assert isinstance(dialog.success_workflow_combo, QComboBox)
    assert isinstance(dialog.timeout_workflow_combo, QComboBox)
    assert dialog.target_step_combo.itemText(0) == "01. 后续步骤"
    assert dialog.target_workflow_combo.itemText(0) == "01. 主组 / 01. 当前流程"

    dialog.template_combo.setCurrentIndex(
        dialog.template_combo.findData("success_timeout_branches")
    )
    dialog.name_edit.setText("分支")
    dialog.success_workflow_combo.setCurrentIndex(
        dialog.success_workflow_combo.findData(success.id)
    )
    dialog.timeout_workflow_combo.setCurrentIndex(
        dialog.timeout_workflow_combo.findData(timeout.id)
    )
    dialog.accept()

    candidate = _project_with_step(project, current.id, dialog.step())
    assert dialog.result() == dialog.DialogCode.Accepted
    assert candidate.validate_references() == []


def test_main_window_adds_template_step_and_opens_property_editor(qtbot):
    project, current, _target_step, _success, _timeout = _project()
    created = AutomationStep(name="模板步骤")
    window = MainWindow(project, create_template_step=lambda: created)
    qtbot.addWidget(window)
    window.flow_tree.select_workflow(current.id)

    window.add_template_step_action.trigger()

    updated = next(
        workflow
        for group in window.view_model.project.groups
        for workflow in group.workflows
        if workflow.id == current.id
    )
    assert updated.steps[-1] == created
    assert window.property_panel.step_id == created.id


def test_template_builder_rejects_missing_project_target():
    templates = importlib.import_module("flow_runner.ui.step_templates")
    project, current, _target_step, _success, _timeout = _project()

    with pytest.raises(ValueError, match="目标流程不存在"):
        templates.build_template_step(
            "jump_after_two_runs",
            {
                "name": "坏引用",
                "target_workflow_id": AutomationStep(name="x").id,
            },
            project=project,
            current_workflow_id=current.id,
        )

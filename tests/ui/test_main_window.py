from uuid import uuid4

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QScrollArea

from flow_runner.domain.enums import StepOutcome
from flow_runner.domain.errors import ConfigurationError
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
from flow_runner.infrastructure.persistence.project_store import ProjectStore
from flow_runner.ui.dialogs.close_confirmation_dialog import (
    CloseConfirmationDialog,
    CloseDecision,
)
from flow_runner.ui.dialogs.parallel_block_dialog import ParallelBlockDialog
from flow_runner.ui.main_window import MainWindow
from flow_runner.ui.runner_bridge import RunnerBridge
from flow_runner.ui.view_models.project_view_model import ProjectViewModel


def sample_project():
    workflow = Workflow(
        name="流程1",
        steps=[AutomationStep(name="检测"), AutomationStep(name="点击")],
    )
    return Project(name="挂机", groups=[FlowGroup(name="组A", workflows=[workflow])])


def selected_step_window(qtbot):
    project = sample_project()
    workflow = project.groups[0].workflows[0]
    step = workflow.steps[0]
    window = MainWindow(project)
    qtbot.addWidget(window)
    window.flow_tree.select_workflow(workflow.id)
    window.step_list.select_step(step.id)
    return window, workflow, step


class _FakeSignal:
    def connect(self, _slot):
        return None


class _FakeRunnerBridge:
    def __init__(self, *, running=True, shutdown_result=True):
        self.eventReceived = _FakeSignal()
        self.failed = _FakeSignal()
        self._running = running
        self.shutdown_result = shutdown_result
        self.stop_calls = 0
        self.shutdown_calls = 0

    @property
    def is_running(self):
        return self._running

    def stop(self):
        self.stop_calls += 1

    def shutdown(self, *, timeout_seconds=5.0):
        self.shutdown_calls += 1
        if self.shutdown_result:
            self._running = False
        return self.shutdown_result


def _close_decision(decision, calls):
    def confirm(*, modified=False, running=False):
        calls.append((modified, running))
        return decision

    return confirm


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


def test_property_panel_scrolls_and_initial_window_fits_available_desktop(qtbot):
    window = MainWindow(sample_project())
    qtbot.addWidget(window)

    available = QApplication.primaryScreen().availableGeometry()

    assert isinstance(window.property_panel, QScrollArea)
    assert window.property_panel.widgetResizable()
    assert window.width() <= available.width()
    assert window.height() <= available.height()


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


def test_mark_saved_starts_a_new_undo_boundary(qtbot):
    model = ProjectViewModel(sample_project())
    group_id = model.project.groups[0].id
    model.rename_group(group_id, "已保存")
    model.mark_saved()
    model.rename_group(group_id, "保存后修改")

    model.undo()
    assert model.project.groups[0].name == "已保存"
    assert not model.dirty
    assert not model.can_undo

    model.undo()
    assert model.project.groups[0].name == "已保存"


def test_project_view_model_copies_step_workflow_and_group_after_source(qtbot):
    project = sample_project()
    group = project.groups[0]
    workflow = group.workflows[0]
    step = workflow.steps[0]
    model = ProjectViewModel(project)

    copied_step = model.copy_step(workflow.id, step.id)

    assert model.project.groups[0].workflows[0].steps[1] == copied_step
    assert copied_step.id != step.id
    model.undo()
    assert model.project == project

    copied_workflow = model.copy_workflow(group.id, workflow.id)

    assert model.project.groups[0].workflows[1] == copied_workflow
    assert copied_workflow.id != workflow.id
    model.undo()
    assert model.project == project

    copied_group = model.copy_group(group.id)

    assert model.project.groups[1] == copied_group
    assert copied_group.id != group.id
    model.undo()
    assert model.project == project


def test_copied_group_saves_reloads_with_unique_ids_and_undoes(qtbot, tmp_path):
    project = sample_project()
    model = ProjectViewModel(project)
    copied = model.copy_group(project.groups[0].id)
    path = tmp_path / "project.json"

    ProjectStore(path).save(model.project)
    loaded = ProjectStore(path).load()

    workflow_ids = [workflow.id for group in loaded.groups for workflow in group.workflows]
    step_ids = [
        step.id
        for group in loaded.groups
        for workflow in group.workflows
        for step in workflow.steps
    ]
    assert len(workflow_ids) == len(set(workflow_ids))
    assert len(step_ids) == len(set(step_ids))
    assert loaded.validate_references() == []
    model.undo()
    assert all(group.id != copied.id for group in model.project.groups)


def test_copy_actions_follow_selection_and_select_created_items(qtbot):
    project = sample_project()
    group = project.groups[0]
    workflow = group.workflows[0]
    step = workflow.steps[0]
    window = MainWindow(project)
    qtbot.addWidget(window)

    assert not window.copy_step_action.isEnabled()
    assert not window.copy_workflow_action.isEnabled()
    assert not window.copy_group_action.isEnabled()

    window.flow_tree.select_group(group.id)
    assert window.copy_group_action.isEnabled()
    assert not window.copy_workflow_action.isEnabled()
    assert not window.copy_step_action.isEnabled()

    window.flow_tree.select_workflow(workflow.id)
    assert window.copy_workflow_action.isEnabled()
    assert not window.copy_group_action.isEnabled()
    window.step_list.select_step(step.id)
    assert window.copy_step_action.isEnabled()

    window.copy_step_action.trigger()

    copied_step = window.view_model.project.groups[0].workflows[0].steps[1]
    assert copied_step.id != step.id
    assert window.property_panel.step_id == copied_step.id

    window.copy_workflow_action.trigger()
    copied_workflow = window.view_model.project.groups[0].workflows[1]
    assert copied_workflow.id != workflow.id
    assert window.copy_workflow_action.isEnabled()
    assert not window.copy_step_action.isEnabled()

    window.flow_tree.select_group(group.id)
    window.copy_group_action.trigger()
    copied_group = window.view_model.project.groups[1]
    assert copied_group.id != group.id
    assert window.copy_group_action.isEnabled()


def test_toolbar_undo_discards_current_pending_form_before_project_history(qtbot):
    window, _workflow, step = selected_step_window(qtbot)
    window.property_panel.name_edit.setText("尚未应用")

    window.undo_action.trigger()

    assert window.property_panel.name_edit.text() == step.name
    assert not window.property_panel.has_pending_edits
    assert not window.isWindowModified()


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


def test_pending_property_edit_can_cancel_close_before_apply(qtbot):
    project = sample_project()
    workflow = project.groups[0].workflows[0]
    window = MainWindow(project, confirm_close=lambda: "cancel")
    qtbot.addWidget(window)
    window.flow_tree.select_workflow(workflow.id)
    window.step_list.select_step(workflow.steps[0].id)
    window.property_panel.name_edit.setText("尚未应用")
    event = QCloseEvent()

    window.closeEvent(event)

    assert window.property_panel.has_pending_edits
    assert not event.isAccepted()


def test_dirty_close_discard_accepts_event_without_saving(qtbot):
    project = sample_project()
    decisions = []
    saved_projects = []
    window = MainWindow(
        project,
        save_project=saved_projects.append,
        confirm_close=_close_decision("discard_and_close", decisions),
    )
    qtbot.addWidget(window)
    window.view_model.rename_group(project.groups[0].id, "已修改")
    event = QCloseEvent()

    window.closeEvent(event)

    assert decisions == [(True, False)]
    assert event.isAccepted()
    assert saved_projects == []


def test_dirty_close_cancel_keeps_pending_values(qtbot):
    decisions = []
    project = sample_project()
    workflow = project.groups[0].workflows[0]
    window = MainWindow(project, confirm_close=_close_decision("cancel", decisions))
    qtbot.addWidget(window)
    window.flow_tree.select_workflow(workflow.id)
    window.step_list.select_step(workflow.steps[0].id)
    window.property_panel.name_edit.setText("尚未应用")
    event = QCloseEvent()

    window.closeEvent(event)

    assert decisions == [(True, False)]
    assert not event.isAccepted()
    assert window.property_panel.name_edit.text() == "尚未应用"
    assert window.property_panel.has_pending_edits


def test_running_close_cancel_keeps_runner_alive(qtbot):
    decisions = []
    bridge = _FakeRunnerBridge(running=True)
    window = MainWindow(
        sample_project(),
        runner_bridge=bridge,
        confirm_close=_close_decision("cancel", decisions),
    )
    qtbot.addWidget(window)
    event = QCloseEvent()

    window.closeEvent(event)

    assert decisions == [(False, True)]
    assert not event.isAccepted()
    assert bridge.is_running
    assert bridge.stop_calls == 0
    assert bridge.shutdown_calls == 0


def test_running_close_stops_and_waits_before_accepting(qtbot):
    decisions = []
    bridge = _FakeRunnerBridge(running=True, shutdown_result=True)
    window = MainWindow(
        sample_project(),
        runner_bridge=bridge,
        confirm_close=_close_decision("stop_and_close", decisions),
    )
    qtbot.addWidget(window)
    event = QCloseEvent()

    window.closeEvent(event)

    assert decisions == [(False, True)]
    assert bridge.shutdown_calls == 1
    assert not bridge.is_running
    assert event.isAccepted()


def test_running_dirty_close_does_not_stop_when_save_fails(qtbot):
    decisions = []
    save_calls = []
    bridge = _FakeRunnerBridge(running=True)

    def fail_save(project):
        save_calls.append(project)
        raise OSError("磁盘不可写")

    project = sample_project()
    window = MainWindow(
        project,
        runner_bridge=bridge,
        save_project=fail_save,
        confirm_close=_close_decision("save_stop_and_close", decisions),
    )
    qtbot.addWidget(window)
    window.view_model.rename_group(project.groups[0].id, "已修改")
    event = QCloseEvent()

    window.closeEvent(event)

    assert decisions == [(True, True)]
    assert len(save_calls) == 1
    assert not event.isAccepted()
    assert bridge.is_running
    assert bridge.shutdown_calls == 0


def test_close_stays_open_when_runner_shutdown_times_out(qtbot):
    decisions = []
    bridge = _FakeRunnerBridge(running=True, shutdown_result=False)
    window = MainWindow(
        sample_project(),
        runner_bridge=bridge,
        confirm_close=_close_decision("stop_and_close", decisions),
    )
    qtbot.addWidget(window)
    event = QCloseEvent()

    window.closeEvent(event)

    assert decisions == [(False, True)]
    assert not event.isAccepted()
    assert bridge.shutdown_calls == 1
    assert bridge.is_running
    assert "未能停止" in window.statusBar().currentMessage()


def test_close_confirmation_dialog_maps_explicit_discard_button(qtbot):
    dialog = CloseConfirmationDialog(modified=True, running=False)
    qtbot.addWidget(dialog)
    assert isinstance(dialog, QMessageBox)

    discard_button = next(
        button for button in dialog.findChildren(QPushButton) if button.text() == "不保存并关闭"
    )
    qtbot.mouseClick(discard_button, Qt.MouseButton.LeftButton)

    assert dialog.decision is CloseDecision.DISCARD_AND_CLOSE


def test_selecting_another_step_commits_pending_editor_values_in_memory(qtbot):
    project = sample_project()
    workflow = project.groups[0].workflows[0]
    window = MainWindow(project)
    qtbot.addWidget(window)
    window.flow_tree.select_workflow(workflow.id)
    window.step_list.select_step(workflow.steps[0].id)
    window.property_panel.name_edit.setText("已自动提交")

    window.step_list.select_step(workflow.steps[1].id)

    saved_step = window.view_model.project.groups[0].workflows[0].steps[0]
    assert saved_step.name == "已自动提交"
    assert window.view_model.dirty


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


def test_step_toolbar_reorders_steps_without_changing_uuid_route_targets(qtbot):
    target = AutomationStep(name="目标")
    middle = AutomationStep(name="中间")
    source = AutomationStep(
        name="来源",
        routes=[
            RouteRule(
                outcome=StepOutcome.SUCCESS,
                target=RouteTarget.next_step(target.id),
            )
        ],
    )
    workflow = Workflow(name="流程", steps=[source, middle, target])
    project = Project(name="p", groups=[FlowGroup(name="g", workflows=[workflow])])
    window = MainWindow(project)
    qtbot.addWidget(window)
    window.flow_tree.select_workflow(workflow.id)
    window.step_list.select_step(target.id)

    window.move_step_up_action.trigger()

    reordered = window.view_model.project.groups[0].workflows[0]
    assert [step.id for step in reordered.steps] == [source.id, target.id, middle.id]
    assert reordered.steps[0].routes[0].target.step_id == target.id
    assert window.view_model.project.validate_references() == []


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


def test_parallel_block_dialog_edits_existing_block_and_preserves_id(qtbot):
    first = Workflow(name="A")
    second = Workflow(name="B")
    third = Workflow(name="C")
    block = ParallelBlock(name="旧并行", workflow_ids=[first.id, second.id])
    project = Project(
        name="p",
        groups=[FlowGroup(name="g", workflows=[first, second, third])],
        parallel_blocks=[block],
    )
    dialog = ParallelBlockDialog(project, block)
    qtbot.addWidget(dialog)

    checked = {
        dialog.workflow_list.item(index).data(Qt.ItemDataRole.UserRole)
        for index in range(dialog.workflow_list.count())
        if dialog.workflow_list.item(index).checkState() is Qt.CheckState.Checked
    }
    assert dialog.name_edit.text() == "旧并行"
    assert checked == {first.id, second.id}

    dialog.name_edit.setText("新并行")
    for index in range(dialog.workflow_list.count()):
        item = dialog.workflow_list.item(index)
        if item.data(Qt.ItemDataRole.UserRole) in {first.id, third.id}:
            item.setCheckState(Qt.CheckState.Checked)
        else:
            item.setCheckState(Qt.CheckState.Unchecked)
    dialog.accept()

    updated = dialog.block()
    assert updated.id == block.id
    assert updated.name == "新并行"
    assert updated.workflow_ids == [first.id, third.id]


def test_view_model_updates_parallel_block_validates_and_undoes(qtbot):
    first = Workflow(name="A")
    second = Workflow(name="B")
    third = Workflow(name="C")
    block = ParallelBlock(name="旧并行", workflow_ids=[first.id, second.id])
    project = Project(
        name="p",
        groups=[FlowGroup(name="g", workflows=[first, second, third])],
        parallel_blocks=[block],
    )
    model = ProjectViewModel(project)
    updated = ParallelBlock(id=block.id, name="新并行", workflow_ids=[first.id, third.id])

    model.update_parallel_block(updated)

    assert model.project.parallel_blocks == [updated]
    model.undo()
    assert model.project == project

    missing = ParallelBlock(id=uuid4(), name="不存在", workflow_ids=[first.id, second.id])
    with pytest.raises(KeyError):
        model.update_parallel_block(missing)
    invalid = ParallelBlock(id=block.id, name="坏引用", workflow_ids=[first.id, uuid4()])
    with pytest.raises(ConfigurationError, match="missing workflow"):
        model.update_parallel_block(invalid)


def test_edit_parallel_action_updates_tree_and_undo_history(qtbot):
    first = Workflow(name="A")
    second = Workflow(name="B")
    block = ParallelBlock(name="旧并行", workflow_ids=[first.id, second.id])
    project = Project(
        name="p",
        groups=[FlowGroup(name="g", workflows=[first, second])],
        parallel_blocks=[block],
    )
    updated = ParallelBlock(id=block.id, name="新并行", workflow_ids=block.workflow_ids)
    window = MainWindow(project, edit_parallel_block=lambda current: updated)
    qtbot.addWidget(window)

    assert not window.edit_parallel_action.isEnabled()
    window.flow_tree.select_parallel_block(block.id)
    assert window.edit_parallel_action.isEnabled()

    window.edit_parallel_action.trigger()

    assert window.view_model.project.parallel_blocks == [updated]
    assert window.flow_tree.tree.currentItem().text(0) == "新并行"
    window.undo_action.trigger()
    assert window.view_model.project.parallel_blocks == [block]


def test_delete_workflow_blocked_when_parallel_block_depends_on_it(qtbot):
    first = Workflow(name="A")
    second = Workflow(name="B")
    block = ParallelBlock(name="双流程监控", workflow_ids=[first.id, second.id])
    project = Project(
        name="p",
        groups=[FlowGroup(name="g", workflows=[first, second])],
        parallel_blocks=[block],
    )
    confirmations = []
    window = MainWindow(
        project,
        confirm_delete=lambda label: confirmations.append(label) or True,
    )
    qtbot.addWidget(window)
    window.flow_tree.select_workflow(first.id)

    window.delete_flow_action.trigger()

    assert confirmations == []
    assert [workflow.id for workflow in window.view_model.project.groups[0].workflows] == [
        first.id,
        second.id,
    ]
    assert "双流程监控" in window.statusBar().currentMessage()
    assert "编辑或删除" in window.statusBar().currentMessage()


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

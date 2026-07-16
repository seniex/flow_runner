from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel

from flow_runner.domain.actions import ActionSpec
from flow_runner.domain.conditions import LeafCondition
from flow_runner.domain.enums import StepOutcome
from flow_runner.domain.project import AutomationStep, FlowGroup, Project, Workflow
from flow_runner.domain.routing import RouteRule, RouteTarget
from flow_runner.ui.main_window import MainWindow
from flow_runner.ui.panels.step_list_panel import StepCardWidget, StepListPanel


class _Signal:
    def connect(self, slot):
        return None


class _RunnerBridge:
    def __init__(self):
        self.eventReceived = _Signal()
        self.failed = _Signal()
        self.started = []
        self.is_running = False

    def start(self, project, workflow_id):
        self.started.append(workflow_id)


def _project():
    step = AutomationStep(
        name="检测并执行",
        condition=LeafCondition(
            id="ocr",
            capability="vision.ocr",
            config={"keywords": "开始"},
        ),
        actions=[
            ActionSpec(capability="input.keyboard", config={"operation": "press", "key": "F1"}),
            ActionSpec(capability="system.wait", config={"seconds": 1.0}),
        ],
        routes=[RouteRule(outcome=StepOutcome.SUCCESS, target=RouteTarget.end())],
    )
    first = Workflow(name="开始游戏", steps=[step])
    second = Workflow(name="自动战斗", steps=[AutomationStep(name="战斗")])
    project = Project(
        name="p",
        groups=[FlowGroup(name="不思议挂机", workflows=[first, second])],
        settings={"entry_workflow_id": str(second.id)},
    )
    return project, first, second, step


def _project_with_long_multi_route_step():
    target_step = AutomationStep(name="名称很长的目标步骤用于验证自动换行")
    target = Workflow(name="名称很长的目标流程用于验证自动换行", steps=[target_step])
    source_step = AutomationStep(
        name="多路由步骤",
        routes=[
            RouteRule(outcome=outcome, target=RouteTarget.jump_workflow(target.id))
            for outcome in (
                StepOutcome.SUCCESS,
                StepOutcome.NOT_MATCHED,
                StepOutcome.TIMEOUT,
                StepOutcome.FAILURE,
            )
        ],
    )
    source = Workflow(name="来源流程", steps=[source_step])
    project = Project(
        name="p",
        groups=[FlowGroup(name="名称很长的流程组用于验证自动换行", workflows=[source, target])],
    )
    return project, source


def test_main_window_startup_selector_persists_and_controls_start(qtbot):
    project, first, second, _step = _project()
    bridge = _RunnerBridge()
    window = MainWindow(project, runner_bridge=bridge)
    qtbot.addWidget(window)

    assert window.flow_tree.tree.topLevelItem(0).text(0) == "01. 不思议挂机"
    assert window.flow_tree.tree.topLevelItem(0).child(0).text(0) == "01. 开始游戏"
    assert window.startup_group_combo.itemText(0) == "01. 不思议挂机"
    assert window.startup_workflow_combo.itemText(0) == "01. 开始游戏"
    assert window.startup_group_combo.currentData() == project.groups[0].id
    assert window.startup_workflow_combo.currentData() == second.id
    window.flow_tree.select_workflow(second.id)
    window.startup_workflow_combo.setCurrentIndex(window.startup_workflow_combo.findData(first.id))

    assert window.view_model.project.settings["entry_workflow_id"] == str(first.id)
    assert window.view_model.dirty
    window.start_action.trigger()
    assert bridge.started == [first.id]


def test_step_list_keeps_all_cards_expanded_and_titles_visible(qtbot):
    _project_value, first, _second, step = _project()
    second_step = AutomationStep(name="第二步")
    first = first.model_copy(update={"steps": [step, second_step]})
    panel = StepListPanel(_project_value)
    qtbot.addWidget(panel)

    panel.set_workflow(first)
    cards = [panel.list.itemWidget(panel.list.item(index)) for index in range(2)]
    card = cards[0]

    assert isinstance(card, StepCardWidget)
    assert panel.list.item(0).text() == ""
    assert card.number_label.text() == "01."
    assert not card.number_label.isHidden()
    assert card.title_label.text() == step.name
    assert all(item.is_expanded for item in cards)
    assert all(not item.title_label.isHidden() for item in cards)
    assert all(not item.body.isHidden() for item in cards)
    panel.select_step(second_step.id)
    assert all(item.is_expanded for item in cards)
    assert all(not item.title_label.isHidden() for item in cards)
    assert cards[1].property("selected") is True
    assert cards[0].property("selected") is False
    assert card.accessibleName() == step.name
    assert card.findChild(QLabel, "conditionSummaryRow").text().startswith("检测")
    assert len(card.findChildren(QLabel, "actionSummaryRow")) == 2
    assert card.findChild(QLabel, "policySummaryRow").text().startswith("策略")
    assert card.findChild(QLabel, "routeSummaryRow").text().startswith("路由")


def test_step_card_routes_use_numbered_paths_and_explicit_lines(qtbot):
    target_step = AutomationStep(name="目标步骤")
    target = Workflow(name="目标流程", steps=[target_step])
    source_step = AutomationStep(
        name="来源步骤",
        routes=[
            RouteRule(
                outcome=StepOutcome.SUCCESS,
                target=RouteTarget.jump_workflow(target.id),
            ),
            RouteRule(outcome=StepOutcome.FAILURE, target=RouteTarget.end()),
        ],
    )
    source = Workflow(name="来源流程", steps=[source_step])
    project = Project(
        name="p",
        groups=[FlowGroup(name="组", workflows=[source, target])],
    )
    window = MainWindow(project)
    qtbot.addWidget(window)
    window.flow_tree.select_workflow(source.id)
    card = window.step_list.list.itemWidget(window.step_list.list.item(0))

    assert card.findChild(QLabel, "routeSummaryRow").text().splitlines() == [
        "路由 1：成功 → 跳转流程：01. 组 / 02. 目标流程 / 01. 目标步骤",
        "路由 2：失败 → 结束任务",
    ]

    window.flow_tree.select_workflow(target.id)
    empty_route_card = window.step_list.list.itemWidget(window.step_list.list.item(0))
    assert empty_route_card.findChild(QLabel, "routeSummaryRow").text() == (
        "路由：成功时顺序进入下一步骤；其它结果结束"
    )


def test_step_cards_wrap_routes_to_viewport_without_horizontal_scroll(qtbot):
    project, workflow = _project_with_long_multi_route_step()
    panel = StepListPanel(project)
    qtbot.addWidget(panel)
    panel.resize(280, 500)
    panel.set_workflow(workflow)
    panel.show()
    qtbot.wait(1)

    assert panel.list.horizontalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAlwaysOff
    assert panel.list.horizontalScrollBar().maximum() == 0
    item = panel.list.item(0)
    card = panel.list.itemWidget(item)
    route_label = card.findChild(QLabel, "routeSummaryRow")
    assert card.width() <= panel.list.viewport().width()
    assert item.sizeHint().height() >= route_label.geometry().bottom() + 8


def test_step_card_height_reflows_when_step_column_width_changes(qtbot):
    project, workflow = _project_with_long_multi_route_step()
    panel = StepListPanel(project)
    qtbot.addWidget(panel)
    panel.resize(280, 500)
    panel.set_workflow(workflow)
    panel.show()
    qtbot.wait(1)
    narrow_height = panel.list.item(0).sizeHint().height()

    panel.resize(700, 500)
    qtbot.wait(1)

    assert panel.list.item(0).sizeHint().height() < narrow_height


def test_main_window_default_layout_exposes_simple_editor_and_runtime_log(qtbot):
    project, _first, _second, _step = _project()
    window = MainWindow(project)
    qtbot.addWidget(window)

    assert window.centralWidget().objectName() == "simpleWorkspace"
    assert window.runtime_log.objectName() == "runtimeLog"
    assert window.property_panel.objectName() == "propertyPanel"


def test_main_window_restores_three_column_widths_from_project_settings(qtbot):
    project, _first, _second, _step = _project()
    project = project.model_copy(
        update={"settings": {**project.settings, "ui_layout": {"column_widths": [180, 320, 700]}}}
    )
    window = MainWindow(project)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(1)

    assert window.workspace_splitter.count() == 3
    assert window.workspace_splitter.widget(0) is window.flow_column
    assert window.workspace_splitter.widget(1) is window.step_column
    assert window.workspace_splitter.widget(2) is window.property_column
    actual = window.workspace_splitter.sizes()
    assert [round(value / sum(actual), 2) for value in actual] == [0.15, 0.27, 0.58]


def test_main_window_uses_confirmed_default_column_widths(qtbot):
    project, _first, _second, _step = _project()
    window = MainWindow(project)
    qtbot.addWidget(window)
    window.show()
    qtbot.wait(1)

    actual = window.workspace_splitter.sizes()
    actual_ratios = [value / sum(actual) for value in actual]
    expected_ratios = [value / 1660 for value in (249, 259, 1152)]
    assert all(
        abs(actual_ratio - expected_ratio) < 0.003
        for actual_ratio, expected_ratio in zip(actual_ratios, expected_ratios, strict=True)
    )


def test_dragged_column_widths_are_written_only_when_project_is_saved(qtbot):
    project, _first, _second, _step = _project()
    saved = []
    window = MainWindow(project, save_project=saved.append)
    qtbot.addWidget(window)
    window.show()

    window.workspace_splitter.setSizes([210, 410, 810])
    window.workspace_splitter.splitterMoved.emit(210, 1)

    assert not window.view_model.dirty
    assert window.isWindowModified()
    assert window.save_action.isEnabled()
    window.save_action.trigger()

    assert saved[-1].settings["ui_layout"]["column_widths"] == window.workspace_splitter.sizes()
    assert not window.isWindowModified()

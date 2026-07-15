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


def test_step_list_uses_expandable_cards_with_compact_category_rows(qtbot):
    _project_value, first, _second, step = _project()
    panel = StepListPanel()
    qtbot.addWidget(panel)

    panel.set_workflow(first)
    item = panel.list.item(0)
    card = panel.list.itemWidget(item)

    assert isinstance(card, StepCardWidget)
    assert item.text() == ""
    assert card.number_label.text() == "01."
    assert not card.number_label.isHidden()
    assert card.title_label.text() == step.name
    assert not card.title_label.isHidden()
    assert card.body.isHidden()
    assert not card.is_expanded
    panel.select_step(step.id)
    assert card.is_expanded
    assert not card.number_label.isHidden()
    assert card.title_label.isHidden()
    assert not card.body.isHidden()
    assert card.accessibleName() == step.name
    assert card.findChild(QLabel, "conditionSummaryRow").text().startswith("检测")
    assert len(card.findChildren(QLabel, "actionSummaryRow")) == 2
    assert card.findChild(QLabel, "policySummaryRow").text().startswith("策略")
    assert card.findChild(QLabel, "routeSummaryRow").text().startswith("路由")


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
    assert window.workspace_splitter.widget(0) is window.flow_tree
    assert window.workspace_splitter.widget(1) is window.step_list
    assert window.workspace_splitter.widget(2) is window.property_panel
    actual = window.workspace_splitter.sizes()
    assert [round(value / sum(actual), 2) for value in actual] == [0.15, 0.27, 0.58]


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

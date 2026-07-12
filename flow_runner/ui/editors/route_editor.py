import json
from uuid import UUID

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from flow_runner.domain.enums import StepOutcome
from flow_runner.domain.project import Project
from flow_runner.domain.routing import (
    ComparisonOperator,
    RoutePredicate,
    RouteRule,
    RouteTarget,
    RouteTargetKind,
)


class RouteEditor(QWidget):
    def __init__(self, project: Project | None = None) -> None:
        super().__init__()
        self._routes: list[RouteRule] = []
        self.outcome_combo = QComboBox()
        for outcome in StepOutcome:
            self.outcome_combo.addItem(outcome.value, outcome)
        self.target_combo = QComboBox()
        for kind in RouteTargetKind:
            self.target_combo.addItem(kind.value, kind)
        self.workflow_combo = QComboBox()
        if project is not None:
            self.set_project(project)
        self.step_id_edit = QLineEdit()
        self.predicate_source_combo = QComboBox()
        self.predicate_source_combo.addItem("无", "")
        for source in (
            "task_variable",
            "workflow_variable",
            "workflow_count",
            "step_count",
        ):
            self.predicate_source_combo.addItem(source, source)
        self.predicate_key_edit = QLineEdit()
        self.predicate_operator_combo = QComboBox()
        for operator in ComparisonOperator:
            self.predicate_operator_combo.addItem(operator.value, operator)
        self.predicate_expected_edit = QLineEdit()
        self.route_list = QListWidget()
        self.add_button = QPushButton("添加路由")
        self.remove_button = QPushButton("删除路由")
        self.up_button = QPushButton("上移")
        self.down_button = QPushButton("下移")
        self.error_label = QLabel("")
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("结果", self.outcome_combo)
        form.addRow("目标类型", self.target_combo)
        form.addRow("目标流程", self.workflow_combo)
        form.addRow("目标步骤 UUID", self.step_id_edit)
        form.addRow("附加条件来源", self.predicate_source_combo)
        form.addRow("条件键/UUID", self.predicate_key_edit)
        form.addRow("比较", self.predicate_operator_combo)
        form.addRow("期望值（JSON）", self.predicate_expected_edit)
        layout.addLayout(form)
        layout.addWidget(self.route_list)
        buttons = QHBoxLayout()
        for button in (
            self.add_button,
            self.remove_button,
            self.up_button,
            self.down_button,
        ):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        layout.addWidget(self.error_label)
        self.add_button.clicked.connect(self._add_current)
        self.remove_button.clicked.connect(self._remove_current)
        self.up_button.clicked.connect(lambda: self._move_current(-1))
        self.down_button.clicked.connect(lambda: self._move_current(1))

    def set_project(self, project: Project) -> None:
        current = self.workflow_combo.currentData()
        self.workflow_combo.clear()
        for group in project.groups:
            for workflow in group.workflows:
                self.workflow_combo.addItem(f"{group.name} / {workflow.name}", workflow.id)
        if isinstance(current, UUID):
            index = self.workflow_combo.findData(current)
            if index >= 0:
                self.workflow_combo.setCurrentIndex(index)

    def set_routes(self, routes: list[RouteRule]) -> None:
        self._routes = list(routes)
        self._refresh_list()

    def routes(self) -> list[RouteRule]:
        return list(self._routes)

    def _add_current(self) -> None:
        try:
            kind = RouteTargetKind(self.target_combo.currentData())
            target = self._target(kind)
            route = RouteRule(
                outcome=StepOutcome(self.outcome_combo.currentData()),
                target=target,
                predicate=self._predicate(),
            )
        except (ValueError, TypeError) as error:
            self.error_label.setText(str(error))
            return
        self.error_label.clear()
        self._routes.append(route)
        self._refresh_list()
        self.route_list.setCurrentRow(len(self._routes) - 1)

    def _target(self, kind: RouteTargetKind) -> RouteTarget:
        if kind is RouteTargetKind.END:
            return RouteTarget.end()
        if kind is RouteTargetKind.RETURN:
            return RouteTarget.return_to_caller()
        if kind is RouteTargetKind.NEXT_STEP:
            return RouteTarget.next_step(UUID(self.step_id_edit.text().strip()))
        workflow_id = self.workflow_combo.currentData()
        if not isinstance(workflow_id, UUID):
            raise ValueError("请选择目标流程")
        if kind is RouteTargetKind.JUMP_WORKFLOW:
            return RouteTarget.jump_workflow(workflow_id)
        return RouteTarget.call_workflow(workflow_id)

    def _predicate(self) -> RoutePredicate | None:
        source = self.predicate_source_combo.currentData()
        if not source:
            return None
        key = self.predicate_key_edit.text().strip()
        if not key:
            raise ValueError("条件键不能为空")
        expected_text = self.predicate_expected_edit.text().strip()
        if not expected_text:
            raise ValueError("期望值不能为空")
        try:
            expected = json.loads(expected_text)
        except json.JSONDecodeError:
            expected = expected_text
        return RoutePredicate(
            source=source,
            key=key,
            operator=ComparisonOperator(self.predicate_operator_combo.currentData()),
            expected=expected,
        )

    def _remove_current(self) -> None:
        row = self.route_list.currentRow()
        if 0 <= row < len(self._routes):
            self._routes.pop(row)
            self._refresh_list()

    def _move_current(self, direction: int) -> None:
        row = self.route_list.currentRow()
        destination = row + direction
        if not 0 <= row < len(self._routes) or not 0 <= destination < len(self._routes):
            return
        self._routes[row], self._routes[destination] = (
            self._routes[destination],
            self._routes[row],
        )
        self._refresh_list()
        self.route_list.setCurrentRow(destination)

    def _refresh_list(self) -> None:
        self.route_list.clear()
        self.route_list.addItems(
            [f"{route.outcome.value} → {route.target.kind.value}" for route in self._routes]
        )

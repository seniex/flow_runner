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
        self._project: Project | None = None
        self._current_step_id: UUID | None = None
        self._routes: list[RouteRule] = []
        self.outcome_combo = QComboBox()
        for outcome in StepOutcome:
            self.outcome_combo.addItem(outcome.value, outcome)
        self.target_combo = QComboBox()
        for kind in RouteTargetKind:
            self.target_combo.addItem(kind.value, kind)
        self.workflow_combo = QComboBox()
        self.step_combo = QComboBox()
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
        self.predicate_workflow_combo = QComboBox()
        self.predicate_step_combo = QComboBox()
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
        form.addRow("目标步骤", self.step_combo)
        form.addRow("附加条件来源", self.predicate_source_combo)
        form.addRow("变量名称", self.predicate_key_edit)
        form.addRow("计数流程", self.predicate_workflow_combo)
        form.addRow("计数步骤", self.predicate_step_combo)
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
        self.target_combo.currentIndexChanged.connect(lambda _: self._update_controls())
        self.predicate_source_combo.currentIndexChanged.connect(lambda _: self._update_controls())
        if project is not None:
            self.set_project(project)
        self._update_controls()

    def set_project(self, project: Project) -> None:
        self._project = project
        current = self.workflow_combo.currentData()
        predicate_workflow = self.predicate_workflow_combo.currentData()
        predicate_step = self.predicate_step_combo.currentData()
        self.workflow_combo.clear()
        self.predicate_workflow_combo.clear()
        self.predicate_step_combo.clear()
        for group in project.groups:
            for workflow in group.workflows:
                label = f"{group.name} / {workflow.name}"
                self.workflow_combo.addItem(label, workflow.id)
                self.predicate_workflow_combo.addItem(label, workflow.id)
                for step in workflow.steps:
                    self.predicate_step_combo.addItem(
                        f"{label} / {step.name}",
                        step.id,
                    )
        if isinstance(current, UUID):
            index = self.workflow_combo.findData(current)
            if index >= 0:
                self.workflow_combo.setCurrentIndex(index)
        if isinstance(predicate_workflow, UUID):
            index = self.predicate_workflow_combo.findData(predicate_workflow)
            if index >= 0:
                self.predicate_workflow_combo.setCurrentIndex(index)
        if isinstance(predicate_step, UUID):
            index = self.predicate_step_combo.findData(predicate_step)
            if index >= 0:
                self.predicate_step_combo.setCurrentIndex(index)
        self.set_step_context(self._current_step_id)

    def set_step_context(self, step_id: UUID | None) -> None:
        self._current_step_id = step_id
        current_target = self.step_combo.currentData()
        self.step_combo.clear()
        if self._project is None or step_id is None:
            return
        for group in self._project.groups:
            for workflow in group.workflows:
                if not any(step.id == step_id for step in workflow.steps):
                    continue
                for step in workflow.steps:
                    self.step_combo.addItem(step.name, step.id)
                if isinstance(current_target, UUID):
                    index = self.step_combo.findData(current_target)
                    if index >= 0:
                        self.step_combo.setCurrentIndex(index)
                return

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
            step_id = self.step_combo.currentData()
            if not isinstance(step_id, UUID):
                raise ValueError("请选择当前流程中的目标步骤")
            return RouteTarget.next_step(step_id)
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
        if source == "workflow_count":
            key_value = self.predicate_workflow_combo.currentData()
            if not isinstance(key_value, UUID):
                raise ValueError("请选择计数流程")
            key = str(key_value)
        elif source == "step_count":
            key_value = self.predicate_step_combo.currentData()
            if not isinstance(key_value, UUID):
                raise ValueError("请选择计数步骤")
            key = str(key_value)
        else:
            key = self.predicate_key_edit.text().strip()
            if not key:
                raise ValueError("变量名称不能为空")
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

    def _update_controls(self) -> None:
        target = self.target_combo.currentData()
        self.workflow_combo.setVisible(
            target in {RouteTargetKind.JUMP_WORKFLOW, RouteTargetKind.CALL_WORKFLOW}
        )
        self.step_combo.setVisible(target is RouteTargetKind.NEXT_STEP)
        source = self.predicate_source_combo.currentData()
        self.predicate_key_edit.setVisible(source in {"task_variable", "workflow_variable"})
        self.predicate_workflow_combo.setVisible(source == "workflow_count")
        self.predicate_step_combo.setVisible(source == "step_count")

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

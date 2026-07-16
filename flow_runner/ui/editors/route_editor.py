import json
from uuid import UUID

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from flow_runner.display_labels import ProjectDisplayIndex
from flow_runner.domain.enums import StepOutcome
from flow_runner.domain.project import Project
from flow_runner.domain.routing import (
    ComparisonOperator,
    RoutePredicate,
    RouteRule,
    RouteTarget,
    RouteTargetKind,
)
from flow_runner.ui.editors.model_form import BindingFieldEditor
from flow_runner.ui.layouts import CompactFlowLayout
from flow_runner.ui.localization import choice_label
from flow_runner.ui.result_bindings import ResultBindingOption
from flow_runner.ui.route_summaries import format_route_summary
from flow_runner.ui.widgets import FocusWheelComboBox


class RouteEditor(QWidget):
    changed = Signal()

    def __init__(self, project: Project | None = None) -> None:
        super().__init__()
        self._loading = False
        self._current_pending = False
        self._project: Project | None = None
        self._labels: ProjectDisplayIndex | None = None
        self._current_step_id: UUID | None = None
        self._routes: list[RouteRule] = []
        self._binding_options: tuple[ResultBindingOption, ...] = ()
        self.outcome_combo = FocusWheelComboBox()
        for outcome in StepOutcome:
            self.outcome_combo.addItem(choice_label(outcome), outcome)
        self.target_combo = FocusWheelComboBox()
        for kind in RouteTargetKind:
            self.target_combo.addItem(choice_label(kind), kind)
        self.workflow_combo = FocusWheelComboBox()
        self.step_combo = FocusWheelComboBox()
        self.predicate_source_combo = FocusWheelComboBox()
        self.predicate_source_combo.addItem("无", "")
        for source in (
            "task_variable",
            "workflow_variable",
            "workflow_count",
            "step_count",
            "binding",
        ):
            self.predicate_source_combo.addItem(choice_label(source), source)
        self.predicate_key_edit = QLineEdit()
        self.predicate_binding_editor = BindingFieldEditor()
        self.predicate_workflow_combo = FocusWheelComboBox()
        self.predicate_step_combo = FocusWheelComboBox()
        self.predicate_operator_combo = FocusWheelComboBox()
        for operator in ComparisonOperator:
            self.predicate_operator_combo.addItem(choice_label(operator), operator)
        self.predicate_expected_edit = QLineEdit()
        self.route_list = QListWidget()
        self.add_button = QPushButton("添加路由")
        self.update_button = QPushButton("更新路由")
        self.remove_button = QPushButton("删除路由")
        self.up_button = QPushButton("上移")
        self.down_button = QPushButton("下移")
        self.error_label = QLabel("")
        layout = QVBoxLayout(self)
        primary_controls = QWidget()
        primary_controls.setObjectName("routePrimaryControls")
        self.primary_layout = CompactFlowLayout(primary_controls)
        self.primary_layout.addField("结果", self.outcome_combo, "outcome")
        self.primary_layout.addField("目标类型", self.target_combo, "target")
        self.primary_layout.addField("目标流程", self.workflow_combo, "workflow")
        self.primary_layout.addField("目标步骤", self.step_combo, "step")
        layout.addWidget(primary_controls)
        predicate_controls = QWidget()
        predicate_controls.setObjectName("routePredicateControls")
        self.predicate_layout = CompactFlowLayout(predicate_controls)
        self.predicate_layout.addField(
            "附加条件来源", self.predicate_source_combo, "predicate_source"
        )
        self.predicate_layout.addField("变量名称", self.predicate_key_edit, "predicate_key")
        self.predicate_layout.addField(
            "检测结果", self.predicate_binding_editor, "predicate_binding"
        )
        self.predicate_layout.addField(
            "计数流程", self.predicate_workflow_combo, "predicate_workflow"
        )
        self.predicate_layout.addField("计数步骤", self.predicate_step_combo, "predicate_step")
        self.predicate_layout.addField("比较", self.predicate_operator_combo, "predicate_operator")
        self.predicate_layout.addField(
            "期望值（JSON）", self.predicate_expected_edit, "predicate_expected"
        )
        layout.addWidget(predicate_controls)
        layout.addWidget(self.route_list)
        buttons = QHBoxLayout()
        for button in (
            self.add_button,
            self.update_button,
            self.remove_button,
            self.up_button,
            self.down_button,
        ):
            buttons.addWidget(button)
        layout.addLayout(buttons)
        layout.addWidget(self.error_label)
        self.add_button.clicked.connect(self._add_current)
        self.update_button.clicked.connect(self._update_current)
        self.remove_button.clicked.connect(self._remove_current)
        self.up_button.clicked.connect(lambda: self._move_current(-1))
        self.down_button.clicked.connect(lambda: self._move_current(1))
        self.target_combo.currentIndexChanged.connect(lambda _: self._update_controls())
        self.predicate_source_combo.currentIndexChanged.connect(lambda _: self._update_controls())
        self.route_list.currentItemChanged.connect(self._selection_changed)
        for combo in (
            self.outcome_combo,
            self.target_combo,
            self.workflow_combo,
            self.step_combo,
            self.predicate_source_combo,
            self.predicate_workflow_combo,
            self.predicate_step_combo,
            self.predicate_operator_combo,
        ):
            combo.currentIndexChanged.connect(self._mark_changed)
        for line_edit in (self.predicate_key_edit, self.predicate_expected_edit):
            line_edit.textChanged.connect(self._mark_changed)
        self.predicate_binding_editor.changed.connect(self._mark_changed)
        if project is not None:
            self.set_project(project)
        self._update_controls()

    def set_binding_options(self, options: tuple[ResultBindingOption, ...]) -> None:
        self._binding_options = options
        self.predicate_binding_editor.set_options(options)

    def set_project(self, project: Project) -> None:
        self._loading = True
        self._project = project
        self._labels = ProjectDisplayIndex(project)
        current = self.workflow_combo.currentData()
        predicate_workflow = self.predicate_workflow_combo.currentData()
        predicate_step = self.predicate_step_combo.currentData()
        self.workflow_combo.clear()
        self.predicate_workflow_combo.clear()
        self.predicate_step_combo.clear()
        for group in project.groups:
            for workflow in group.workflows:
                label = self._labels.workflow_path(workflow.id)
                self.workflow_combo.addItem(label, str(workflow.id))
                self.predicate_workflow_combo.addItem(label, str(workflow.id))
                for step in workflow.steps:
                    self.predicate_step_combo.addItem(
                        self._labels.step_path(step.id),
                        str(step.id),
                    )
        if current is not None:
            index = _find_uuid_data(self.workflow_combo, current)
            if index >= 0:
                self.workflow_combo.setCurrentIndex(index)
        if predicate_workflow is not None:
            index = _find_uuid_data(self.predicate_workflow_combo, predicate_workflow)
            if index >= 0:
                self.predicate_workflow_combo.setCurrentIndex(index)
        if predicate_step is not None:
            index = _find_uuid_data(self.predicate_step_combo, predicate_step)
            if index >= 0:
                self.predicate_step_combo.setCurrentIndex(index)
        self.set_step_context(self._current_step_id)
        self._update_list_texts()
        self._loading = False

    def set_step_context(self, step_id: UUID | None) -> None:
        previous_step_id = self._current_step_id
        self._current_step_id = step_id
        current_target = self.step_combo.currentData()
        preserve_current_target = (
            previous_step_id == step_id
            and current_target is not None
            and self.target_combo.currentData() == RouteTargetKind.NEXT_STEP
            and 0 <= self.route_list.currentRow() < len(self._routes)
        )
        self.step_combo.clear()
        if self._project is None or step_id is None:
            return
        for group in self._project.groups:
            for workflow in group.workflows:
                current_index = next(
                    (index for index, step in enumerate(workflow.steps) if step.id == step_id),
                    None,
                )
                if current_index is None:
                    continue
                for step in workflow.steps:
                    label = (
                        self._labels.step_label(step.id) if self._labels is not None else step.name
                    )
                    self.step_combo.addItem(label, str(step.id))
                if preserve_current_target:
                    self.step_combo.setCurrentIndex(
                        _find_uuid_data(self.step_combo, current_target)
                    )
                else:
                    next_index = current_index + 1
                    self.step_combo.setCurrentIndex(
                        next_index if next_index < len(workflow.steps) else -1
                    )
                return

    def set_routes(self, routes: list[RouteRule]) -> None:
        self._loading = True
        self._current_pending = False
        self._routes = list(routes)
        self._refresh_list()
        if self._routes:
            self.route_list.setCurrentRow(0)
        self._loading = False
        if self._routes:
            self._load_current(0)

    def routes(self) -> list[RouteRule]:
        return list(self._routes)

    def commit_current(self) -> None:
        row = self.route_list.currentRow()
        if not 0 <= row < len(self._routes):
            return
        self._commit_row(row)

    def _commit_row(self, row: int) -> None:
        route = self._current_route()
        if route is None:
            raise ValueError(self._current_error())
        self._routes[row] = route
        self._current_pending = False
        self._update_list_texts()

    def commit_pending(self) -> None:
        if self._current_pending:
            if not 0 <= self.route_list.currentRow() < len(self._routes):
                raise ValueError("请先添加当前路由")
            self.commit_current()
        self._validate_route_order()

    def _mark_changed(self) -> None:
        if not self._loading:
            self._current_pending = True
            self.changed.emit()

    def _add_current(self) -> None:
        route = self._current_route()
        if route is None:
            return
        self._routes.append(route)
        self._current_pending = False
        self._refresh_and_select(len(self._routes) - 1)
        self.changed.emit()

    def _update_current(self) -> None:
        row = self.route_list.currentRow()
        if not 0 <= row < len(self._routes):
            self.error_label.setText("请先选择要更新的路由")
            return
        route = self._current_route()
        if route is None:
            return
        self._routes[row] = route
        self._current_pending = False
        self._update_list_texts()
        self.changed.emit()

    def _current_route(self) -> RouteRule | None:
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
            return None
        self.error_label.clear()
        return route

    def _selection_changed(
        self,
        current: QListWidgetItem | None,
        previous: QListWidgetItem | None,
    ) -> None:
        if self._loading:
            return
        previous_row = self.route_list.row(previous) if previous is not None else -1
        if self._current_pending and previous is not None and 0 <= previous_row < len(self._routes):
            try:
                self._commit_row(previous_row)
            except ValueError as error:
                self.error_label.setText(str(error))
                self._loading = True
                self.route_list.setCurrentItem(previous)
                self._loading = False
                return
        self._load_current(self.route_list.row(current) if current is not None else -1)

    def _load_current(self, row: int) -> None:
        if not 0 <= row < len(self._routes):
            return
        self._loading = True
        self._current_pending = False
        route = self._routes[row]
        self.outcome_combo.setCurrentIndex(self.outcome_combo.findData(route.outcome))
        self.target_combo.setCurrentIndex(self.target_combo.findData(route.target.kind))
        if route.target.workflow_id is not None:
            self.workflow_combo.setCurrentIndex(
                _find_uuid_data(self.workflow_combo, route.target.workflow_id)
            )
        if route.target.step_id is not None:
            self.step_combo.setCurrentIndex(_find_uuid_data(self.step_combo, route.target.step_id))
        predicate = route.predicate
        source = "" if predicate is None else predicate.source
        self.predicate_source_combo.setCurrentIndex(self.predicate_source_combo.findData(source))
        self.predicate_key_edit.clear()
        self.predicate_binding_editor.setValue("")
        self.predicate_expected_edit.clear()
        if predicate is None:
            self.error_label.clear()
            self._loading = False
            return
        if predicate.source == "workflow_count":
            self.predicate_workflow_combo.setCurrentIndex(
                _find_uuid_data(self.predicate_workflow_combo, predicate.key)
            )
        elif predicate.source == "step_count":
            self.predicate_step_combo.setCurrentIndex(
                _find_uuid_data(self.predicate_step_combo, predicate.key)
            )
        elif predicate.source == "binding":
            self.predicate_binding_editor.setValue(predicate.key)
        else:
            self.predicate_key_edit.setText(predicate.key)
        self.predicate_operator_combo.setCurrentIndex(
            self.predicate_operator_combo.findData(predicate.operator)
        )
        self.predicate_expected_edit.setText(json.dumps(predicate.expected, ensure_ascii=False))
        self.error_label.clear()
        self._loading = False

    def _current_error(self) -> str:
        outcome = choice_label(self.outcome_combo.currentData())
        target = choice_label(self.target_combo.currentData())
        detail = self.error_label.text() or "路由配置无效"
        if detail.startswith("请选择"):
            detail = f"未选择{detail.removeprefix('请选择')}"
        else:
            detail = f"：{detail}"
        return f"路由“{outcome} → {target}”{detail}"

    def _target(self, kind: RouteTargetKind) -> RouteTarget:
        if kind is RouteTargetKind.END:
            return RouteTarget.end()
        if kind is RouteTargetKind.RETURN:
            return RouteTarget.return_to_caller()
        if kind is RouteTargetKind.NEXT_STEP:
            step_id = _uuid_from_combo(self.step_combo, "请选择当前流程中的目标步骤")
            return RouteTarget.next_step(step_id)
        workflow_id = _uuid_from_combo(self.workflow_combo, "请选择目标流程")
        if kind is RouteTargetKind.JUMP_WORKFLOW:
            return RouteTarget.jump_workflow(workflow_id)
        return RouteTarget.call_workflow(workflow_id)

    def _predicate(self) -> RoutePredicate | None:
        source = self.predicate_source_combo.currentData()
        if not source:
            return None
        if source == "workflow_count":
            key = str(_uuid_from_combo(self.predicate_workflow_combo, "请选择计数流程"))
        elif source == "step_count":
            key = str(_uuid_from_combo(self.predicate_step_combo, "请选择计数步骤"))
        elif source == "binding":
            key = self.predicate_binding_editor.value()
            if not key:
                raise ValueError("绑定表达式不能为空")
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
        self.primary_layout.setFieldVisible(
            self.workflow_combo,
            target in {RouteTargetKind.JUMP_WORKFLOW, RouteTargetKind.CALL_WORKFLOW},
        )
        self.primary_layout.setFieldVisible(self.step_combo, target == RouteTargetKind.NEXT_STEP)
        source = self.predicate_source_combo.currentData()
        self._populate_predicate_operators(source)
        self.predicate_layout.setFieldVisible(
            self.predicate_key_edit,
            source in {"task_variable", "workflow_variable"},
        )
        self.predicate_layout.setFieldVisible(
            self.predicate_binding_editor,
            source == "binding",
        )
        self.predicate_layout.setFieldVisible(
            self.predicate_workflow_combo, source == "workflow_count"
        )
        self.predicate_layout.setFieldVisible(self.predicate_step_combo, source == "step_count")
        predicate_enabled = bool(source)
        self.predicate_layout.setFieldVisible(self.predicate_operator_combo, predicate_enabled)
        self.predicate_layout.setFieldVisible(self.predicate_expected_edit, predicate_enabled)

    def _populate_predicate_operators(self, source: object) -> None:
        current = self.predicate_operator_combo.currentData()
        operators = list(ComparisonOperator)
        if source in {"workflow_count", "step_count"}:
            operators = [
                operator
                for operator in operators
                if operator not in {ComparisonOperator.CONTAINS, ComparisonOperator.MATCHES}
            ]
        if self.predicate_operator_combo.count() == len(operators) and all(
            self.predicate_operator_combo.itemData(index) == operator
            for index, operator in enumerate(operators)
        ):
            return
        self.predicate_operator_combo.clear()
        for operator in operators:
            self.predicate_operator_combo.addItem(choice_label(operator), operator)
        selected = self.predicate_operator_combo.findData(current)
        if selected < 0:
            selected = self.predicate_operator_combo.findData(ComparisonOperator.EQ)
        self.predicate_operator_combo.setCurrentIndex(selected)

    def _remove_current(self) -> None:
        row = self.route_list.currentRow()
        if 0 <= row < len(self._routes):
            self._routes.pop(row)
            self._current_pending = False
            self._refresh_and_select(min(row, len(self._routes) - 1))
            self.changed.emit()

    def _move_current(self, direction: int) -> None:
        row = self.route_list.currentRow()
        destination = row + direction
        if not 0 <= row < len(self._routes) or not 0 <= destination < len(self._routes):
            return
        try:
            self.commit_pending()
        except ValueError as error:
            self.error_label.setText(str(error))
            return
        self._routes[row], self._routes[destination] = (
            self._routes[destination],
            self._routes[row],
        )
        self._current_pending = False
        self._refresh_and_select(destination)
        self.changed.emit()

    def _refresh_and_select(self, row: int) -> None:
        self._loading = True
        self._refresh_list()
        if row >= 0:
            self.route_list.setCurrentRow(row)
        self._loading = False
        self._load_current(row)

    def _refresh_list(self) -> None:
        self.route_list.clear()
        self.route_list.addItems(
            [self._route_summary(route, index) for index, route in enumerate(self._routes)]
        )

    def _update_list_texts(self) -> None:
        for index, route in enumerate(self._routes):
            item = self.route_list.item(index)
            if item is not None:
                item.setText(self._route_summary(route, index))

    def _route_summary(self, route: RouteRule, index: int) -> str:
        labels = self._labels or ProjectDisplayIndex(Project(name="空项目"))
        binding_labels = {option.expression: option.label for option in self._binding_options}
        return format_route_summary(
            route,
            index,
            self._routes,
            labels=labels,
            binding_labels=binding_labels,
        )

    def _validate_route_order(self) -> None:
        unconditional: dict[StepOutcome, int] = {}
        for index, route in enumerate(self._routes):
            if route.predicate is None:
                unconditional.setdefault(route.outcome, index)
                continue
            shadowing_index = unconditional.get(route.outcome)
            if shadowing_index is not None:
                raise ValueError(
                    f"第 {index + 1} 条路由被第 {shadowing_index + 1} 条同结果无条件路由遮挡"
                )


def _find_uuid_data(combo: QComboBox, value: object) -> int:
    try:
        normalized = str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return -1
    for index in range(combo.count()):
        if combo.itemData(index) == normalized:
            return index
    return -1


def _uuid_from_combo(combo: QComboBox, error: str) -> UUID:
    value = combo.currentData()
    try:
        return UUID(value) if isinstance(value, str) else UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise ValueError(error) from None

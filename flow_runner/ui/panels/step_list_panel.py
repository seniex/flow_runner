from uuid import UUID

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from flow_runner.display_labels import ProjectDisplayIndex
from flow_runner.domain.conditions import ConditionGroup, LeafCondition
from flow_runner.domain.project import AutomationStep, Project, Workflow
from flow_runner.ui.localization import action_summary, capability_label, choice_label
from flow_runner.ui.result_bindings import result_binding_options
from flow_runner.ui.route_summaries import format_route_summaries


class StepCardWidget(QWidget):
    clicked = Signal()

    def __init__(
        self,
        step: AutomationStep,
        index: int,
        labels: ProjectDisplayIndex | None = None,
    ) -> None:
        super().__init__()
        self.setObjectName("stepCard")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAccessibleName(step.name)
        self.setProperty("selected", False)
        self.is_expanded = True

        self.number_label = QLabel(f"{index:02d}.")
        self.number_label.setObjectName("stepCardNumber")
        self.title_label = QLabel(step.name)
        self.title_label.setObjectName("stepCardTitle")
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(6)
        header_layout.addWidget(self.number_label)
        header_layout.addWidget(self.title_label, 1)
        self.body = QWidget()
        self.body.setObjectName("stepCardBody")
        body_layout = QVBoxLayout(self.body)
        body_layout.setContentsMargins(0, 4, 0, 0)
        body_layout.setSpacing(3)
        body_layout.addWidget(_summary_label(_condition_summary(step), "conditionSummaryRow"))
        binding_labels = {
            option.expression: option.label for option in result_binding_options(step.condition)
        }
        route_labels = labels or ProjectDisplayIndex(Project(name="空项目"))
        for action in step.actions:
            body_layout.addWidget(
                _summary_label(
                    f"执行：{action_summary(action, binding_labels=binding_labels)}",
                    "actionSummaryRow",
                )
            )
        if not step.actions:
            body_layout.addWidget(_summary_label("执行：无", "actionSummaryRow"))
        body_layout.addWidget(_summary_label(_policy_summary(step), "policySummaryRow"))
        body_layout.addWidget(
            _summary_label(
                "\n".join(
                    format_route_summaries(
                        step.routes,
                        labels=route_labels,
                        binding_labels=binding_labels,
                    )
                ),
                "routeSummaryRow",
            )
        )
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(0)
        layout.addWidget(header)
        layout.addWidget(self.body)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() is Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


def _summary_label(text: str, object_name: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName(object_name)
    label.setWordWrap(True)
    return label


def _condition_summary(step: AutomationStep) -> str:
    condition = step.condition
    if condition is None:
        return "检测：无"
    if isinstance(condition, LeafCondition):
        detail = condition.config.get("keywords") or condition.config.get("template_path") or ""
        suffix = f" · {detail}" if detail else ""
        return f"检测：{capability_label(condition.capability)}{suffix}"
    if isinstance(condition, ConditionGroup):
        operator = {"and": "且", "or": "或", "not": "非"}[condition.operator]
        return f"检测：{operator}组合（{len(condition.children)} 项）"
    return "检测：已配置"


def _policy_summary(step: AutomationStep) -> str:
    condition = step.condition_policy
    action = step.action_policy
    parts = [choice_label(condition.mode)]
    if condition.max_attempts is not None:
        parts.append(f"检测 {condition.max_attempts} 次")
    if action.max_attempts > 1:
        parts.append(f"执行 {action.max_attempts} 次")
    return f"策略：{' · '.join(parts)}"


class StepListPanel(QWidget):
    stepSelected = Signal(object)

    def __init__(self, project: Project) -> None:
        super().__init__()
        self.setObjectName("stepListPanel")
        self.list = QListWidget()
        layout = QVBoxLayout(self)
        layout.addWidget(self.list)
        self._items: dict[UUID, QListWidgetItem] = {}
        self.list.currentItemChanged.connect(self._on_current_item)
        self.set_project(project)

    def set_project(self, project: Project) -> None:
        self._project = project
        self._labels = ProjectDisplayIndex(project)

    def set_workflow(self, workflow: Workflow) -> None:
        self.list.clear()
        self._items.clear()
        for index, step in enumerate(workflow.steps, start=1):
            item = QListWidgetItem("")
            item.setData(Qt.ItemDataRole.UserRole, step.id)
            item.setData(Qt.ItemDataRole.AccessibleTextRole, step.name)
            self.list.addItem(item)
            card = StepCardWidget(step, index, self._labels)
            card.clicked.connect(lambda step_item=item: self.list.setCurrentItem(step_item))
            self.list.setItemWidget(item, card)
            item.setSizeHint(card.sizeHint())
            self._items[step.id] = item

    def select_step(self, step_id: UUID) -> None:
        self.list.setCurrentItem(self._items[step_id])

    def _on_current_item(self, current: QListWidgetItem | None) -> None:
        for item in self._items.values():
            card = self.list.itemWidget(item)
            if isinstance(card, StepCardWidget):
                card.set_selected(item is current)
                item.setSizeHint(card.sizeHint())
        if current is None:
            return
        step_id = current.data(Qt.ItemDataRole.UserRole)
        if isinstance(step_id, UUID):
            self.stepSelected.emit(step_id)

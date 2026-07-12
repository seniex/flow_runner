from collections.abc import Callable
from uuid import UUID

from PySide6.QtCore import QObject, Signal

from flow_runner.domain.errors import ConfigurationError
from flow_runner.domain.project import AutomationStep, FlowGroup, Project, Workflow


class ProjectViewModel(QObject):
    projectChanged = Signal(object)

    def __init__(self, project: Project) -> None:
        super().__init__()
        self.project = project
        self._saved_project = project
        self._undo_stack: list[Project] = []
        self.dirty = False

    def mark_saved(self) -> None:
        self._saved_project = self.project
        self.dirty = False

    def add_group(self, group: FlowGroup) -> None:
        self._commit(self.project.model_copy(update={"groups": [*self.project.groups, group]}))

    def rename_group(self, group_id: UUID, name: str) -> None:
        groups = [
            FlowGroup(id=group.id, name=name, workflows=group.workflows)
            if group.id == group_id
            else group
            for group in self.project.groups
        ]
        if not any(group.id == group_id for group in self.project.groups):
            raise KeyError(group_id)
        self._commit(self.project.model_copy(update={"groups": groups}))

    def remove_group(self, group_id: UUID) -> None:
        groups = [group for group in self.project.groups if group.id != group_id]
        if len(groups) == len(self.project.groups):
            raise KeyError(group_id)
        self._commit(self.project.model_copy(update={"groups": groups}))

    def add_workflow(self, group_id: UUID, workflow: Workflow) -> None:
        groups: list[FlowGroup] = []
        found = False
        for group in self.project.groups:
            if group.id == group_id:
                found = True
                group = FlowGroup(
                    id=group.id,
                    name=group.name,
                    workflows=[*group.workflows, workflow],
                )
            groups.append(group)
        if not found:
            raise KeyError(group_id)
        self._commit(self.project.model_copy(update={"groups": groups}))

    def rename_workflow(self, workflow_id: UUID, name: str) -> None:
        self._replace_workflow(
            workflow_id,
            lambda workflow: Workflow(id=workflow.id, name=name, steps=workflow.steps),
        )

    def remove_workflow(self, workflow_id: UUID) -> None:
        groups: list[FlowGroup] = []
        found = False
        for group in self.project.groups:
            workflows = [workflow for workflow in group.workflows if workflow.id != workflow_id]
            if len(workflows) != len(group.workflows):
                found = True
                group = FlowGroup(id=group.id, name=group.name, workflows=workflows)
            groups.append(group)
        if not found:
            raise KeyError(workflow_id)
        self._commit(self.project.model_copy(update={"groups": groups}))

    def add_step(self, workflow_id: UUID, step: AutomationStep) -> None:
        self._replace_workflow(
            workflow_id,
            lambda workflow: Workflow(
                id=workflow.id,
                name=workflow.name,
                steps=[*workflow.steps, step],
            ),
        )

    def update_step(self, workflow_id: UUID, step: AutomationStep) -> None:
        def replace(workflow: Workflow) -> Workflow:
            if not any(existing.id == step.id for existing in workflow.steps):
                raise KeyError(step.id)
            return Workflow(
                id=workflow.id,
                name=workflow.name,
                steps=[step if existing.id == step.id else existing for existing in workflow.steps],
            )

        self._replace_workflow(workflow_id, replace)

    def remove_step(self, workflow_id: UUID, step_id: UUID) -> None:
        def remove(workflow: Workflow) -> Workflow:
            steps = [step for step in workflow.steps if step.id != step_id]
            if len(steps) == len(workflow.steps):
                raise KeyError(step_id)
            return Workflow(id=workflow.id, name=workflow.name, steps=steps)

        self._replace_workflow(workflow_id, remove)

    def move_step(self, workflow_id: UUID, step_id: UUID, direction: int) -> None:
        def move(workflow: Workflow) -> Workflow:
            steps = list(workflow.steps)
            index = next((i for i, step in enumerate(steps) if step.id == step_id), None)
            if index is None:
                raise KeyError(step_id)
            destination = index + direction
            if not 0 <= destination < len(steps):
                return workflow
            steps[index], steps[destination] = steps[destination], steps[index]
            return Workflow(id=workflow.id, name=workflow.name, steps=steps)

        self._replace_workflow(workflow_id, move)

    def undo(self) -> None:
        if not self._undo_stack:
            return
        self.project = self._undo_stack.pop()
        self.dirty = self.project != self._saved_project
        self.projectChanged.emit(self.project)

    def move_workflow(self, workflow_id: UUID, direction: int) -> None:
        groups = list(self.project.groups)
        for group_index, group in enumerate(groups):
            workflows = list(group.workflows)
            for index, workflow in enumerate(workflows):
                if workflow.id != workflow_id:
                    continue
                destination = index + direction
                if not 0 <= destination < len(workflows):
                    return
                workflows[index], workflows[destination] = (
                    workflows[destination],
                    workflows[index],
                )
                groups[group_index] = FlowGroup(
                    id=group.id,
                    name=group.name,
                    workflows=workflows,
                )
                self._commit(self.project.model_copy(update={"groups": groups}))
                return

    def _replace_workflow(
        self,
        workflow_id: UUID,
        replacement: Callable[[Workflow], Workflow],
    ) -> None:
        groups: list[FlowGroup] = []
        found = False
        for group in self.project.groups:
            workflows: list[Workflow] = []
            for workflow in group.workflows:
                if workflow.id == workflow_id:
                    found = True
                    workflow = replacement(workflow)
                workflows.append(workflow)
            groups.append(FlowGroup(id=group.id, name=group.name, workflows=workflows))
        if not found:
            raise KeyError(workflow_id)
        self._commit(self.project.model_copy(update={"groups": groups}))

    def _commit(self, project: Project) -> None:
        if project == self.project:
            return
        errors = project.validate_references()
        if errors:
            raise ConfigurationError("; ".join(errors))
        self._undo_stack.append(self.project)
        self.project = project
        self.dirty = self.project != self._saved_project
        self.projectChanged.emit(self.project)

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from flow_runner.domain.project import Project


@dataclass(frozen=True, slots=True)
class NumberedName:
    index: int
    name: str

    @property
    def label(self) -> str:
        return f"{self.index:02d}. {self.name}"


class ProjectDisplayIndex:
    def __init__(self, project: Project) -> None:
        self._groups: dict[UUID, NumberedName] = {}
        self._workflows: dict[UUID, NumberedName] = {}
        self._steps: dict[UUID, NumberedName] = {}
        self._workflow_groups: dict[UUID, UUID] = {}
        self._step_workflows: dict[UUID, UUID] = {}
        self._workflow_entry_steps: dict[UUID, UUID] = {}
        for group_index, group in enumerate(project.groups, start=1):
            self._groups[group.id] = NumberedName(group_index, group.name)
            for workflow_index, workflow in enumerate(group.workflows, start=1):
                self._workflows[workflow.id] = NumberedName(workflow_index, workflow.name)
                self._workflow_groups[workflow.id] = group.id
                if workflow.steps:
                    self._workflow_entry_steps[workflow.id] = workflow.steps[0].id
                for step_index, step in enumerate(workflow.steps, start=1):
                    self._steps[step.id] = NumberedName(step_index, step.name)
                    self._step_workflows[step.id] = workflow.id

    def group_label(self, group_id: UUID) -> str:
        item = self._groups.get(group_id)
        return item.label if item is not None else "未知流程组"

    def workflow_label(self, workflow_id: UUID) -> str:
        item = self._workflows.get(workflow_id)
        return item.label if item is not None else "未知流程"

    def step_label(self, step_id: UUID) -> str:
        item = self._steps.get(step_id)
        return item.label if item is not None else "未知步骤"

    def workflow_path(self, workflow_id: UUID) -> str:
        group_id = self._workflow_groups.get(workflow_id)
        if group_id is None:
            return self.workflow_label(workflow_id)
        return f"{self.group_label(group_id)} / {self.workflow_label(workflow_id)}"

    def step_path(self, step_id: UUID) -> str:
        workflow_id = self._step_workflows.get(step_id)
        if workflow_id is None:
            return self.step_label(step_id)
        return f"{self.workflow_path(workflow_id)} / {self.step_label(step_id)}"

    def workflow_id_for_step(self, step_id: UUID) -> UUID | None:
        return self._step_workflows.get(step_id)

    def workflow_entry_path(self, workflow_id: UUID) -> str:
        step_id = self._workflow_entry_steps.get(workflow_id)
        return self.step_path(step_id) if step_id is not None else self.workflow_path(workflow_id)

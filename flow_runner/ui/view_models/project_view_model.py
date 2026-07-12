from uuid import UUID

from PySide6.QtCore import QObject, Signal

from flow_runner.domain.project import FlowGroup, Project


class ProjectViewModel(QObject):
    projectChanged = Signal(object)

    def __init__(self, project: Project) -> None:
        super().__init__()
        self.project = project

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
                self.project = self.project.model_copy(update={"groups": groups})
                self.projectChanged.emit(self.project)
                return

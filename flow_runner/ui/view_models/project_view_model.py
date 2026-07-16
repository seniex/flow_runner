from collections.abc import Callable
from uuid import UUID

from PySide6.QtCore import QObject, Signal

from flow_runner.domain.cloning import clone_group, clone_step, clone_workflow
from flow_runner.domain.errors import ConfigurationError
from flow_runner.domain.project import (
    AutomationStep,
    FlowGroup,
    ParallelBlock,
    Project,
    Workflow,
)
from flow_runner.domain.routing import RouteRule, RouteTargetKind


class ProjectViewModel(QObject):
    projectChanged = Signal(object)
    historyChanged = Signal(bool)

    def __init__(self, project: Project) -> None:
        super().__init__()
        self.project = project
        self._saved_project = project
        self._undo_stack: list[Project] = []
        self.dirty = False

    @property
    def can_undo(self) -> bool:
        return bool(self._undo_stack)

    def mark_saved(self) -> None:
        self._saved_project = self.project
        self._undo_stack.clear()
        self.dirty = False
        self.historyChanged.emit(False)

    def update_settings(self, settings: dict[str, object]) -> None:
        self._commit(self.project.model_copy(update={"settings": dict(settings)}))

    def add_parallel_block(self, block: ParallelBlock) -> None:
        self._commit(
            self.project.model_copy(
                update={"parallel_blocks": [*self.project.parallel_blocks, block]}
            )
        )

    def update_parallel_block(self, block: ParallelBlock) -> None:
        validated = ParallelBlock.model_validate(block.model_dump(mode="python"))
        blocks = [
            validated if existing.id == validated.id else existing
            for existing in self.project.parallel_blocks
        ]
        if not any(existing.id == validated.id for existing in self.project.parallel_blocks):
            raise KeyError(validated.id)
        self._commit(self.project.model_copy(update={"parallel_blocks": blocks}))

    def remove_parallel_block(self, block_id: UUID) -> None:
        blocks = [block for block in self.project.parallel_blocks if block.id != block_id]
        if len(blocks) == len(self.project.parallel_blocks):
            raise KeyError(block_id)
        self._commit(self.project.model_copy(update={"parallel_blocks": blocks}))

    def add_group(self, group: FlowGroup) -> None:
        self._commit(self.project.model_copy(update={"groups": [*self.project.groups, group]}))

    def copy_group(self, group_id: UUID) -> FlowGroup:
        groups = list(self.project.groups)
        index = next((index for index, group in enumerate(groups) if group.id == group_id), None)
        if index is None:
            raise KeyError(group_id)
        copied = clone_group(groups[index])
        groups.insert(index + 1, copied)
        self._commit(self.project.model_copy(update={"groups": groups}))
        return copied

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

    def copy_workflow(self, group_id: UUID, workflow_id: UUID) -> Workflow:
        groups: list[FlowGroup] = []
        copied: Workflow | None = None
        for group in self.project.groups:
            if group.id != group_id:
                groups.append(group)
                continue
            workflows = list(group.workflows)
            index = next(
                (index for index, workflow in enumerate(workflows) if workflow.id == workflow_id),
                None,
            )
            if index is None:
                raise KeyError(workflow_id)
            copied = clone_workflow(workflows[index])
            workflows.insert(index + 1, copied)
            groups.append(FlowGroup(id=group.id, name=group.name, workflows=workflows))
        if copied is None:
            raise KeyError(group_id)
        self._commit(self.project.model_copy(update={"groups": groups}))
        return copied

    def rename_workflow(self, workflow_id: UUID, name: str) -> None:
        self._replace_workflow(
            workflow_id,
            lambda workflow: Workflow(id=workflow.id, name=name, steps=workflow.steps),
        )

    @staticmethod
    def _route_references_workflow(route: RouteRule, workflow_id: UUID) -> bool:
        target = route.target
        if (
            target.kind in {RouteTargetKind.JUMP_WORKFLOW, RouteTargetKind.CALL_WORKFLOW}
            and target.workflow_id == workflow_id
        ):
            return True
        predicate = route.predicate
        return (
            predicate is not None
            and predicate.source == "workflow_count"
            and predicate.key == str(workflow_id)
        )

    def workflow_route_reference_count(self, workflow_id: UUID) -> int:
        return sum(
            self._route_references_workflow(route, workflow_id)
            for group in self.project.groups
            for workflow in group.workflows
            if workflow.id != workflow_id
            for step in workflow.steps
            for route in step.routes
        )

    def remove_workflow(self, workflow_id: UUID) -> int:
        dependencies = [
            block.name
            for block in self.project.parallel_blocks
            if workflow_id in block.workflow_ids
        ]
        if dependencies:
            raise ConfigurationError(
                f"流程仍被并行监控块引用：{'、'.join(dependencies)}；请先编辑或删除这些并行块"
            )
        groups: list[FlowGroup] = []
        found = False
        for group in self.project.groups:
            workflows: list[Workflow] = []
            for workflow in group.workflows:
                if workflow.id == workflow_id:
                    found = True
                    continue
                steps: list[AutomationStep] = []
                for step in workflow.steps:
                    routes = [
                        route
                        for route in step.routes
                        if not self._route_references_workflow(route, workflow_id)
                    ]
                    steps.append(step.model_copy(update={"routes": routes}))
                workflows.append(workflow.model_copy(update={"steps": steps}))
            groups.append(group.model_copy(update={"workflows": workflows}))
        if not found:
            raise KeyError(workflow_id)

        settings = dict(self.project.settings)
        if settings.get("entry_workflow_id") == str(workflow_id):
            first_workflow = next(
                (workflow for group in groups for workflow in group.workflows),
                None,
            )
            if first_workflow is None:
                settings.pop("entry_workflow_id", None)
            else:
                settings["entry_workflow_id"] = str(first_workflow.id)

        removed_routes = self.workflow_route_reference_count(workflow_id)
        self._commit(self.project.model_copy(update={"groups": groups, "settings": settings}))
        return removed_routes

    def add_step(self, workflow_id: UUID, step: AutomationStep) -> None:
        self._replace_workflow(
            workflow_id,
            lambda workflow: Workflow(
                id=workflow.id,
                name=workflow.name,
                steps=[*workflow.steps, step],
            ),
        )

    def copy_step(self, workflow_id: UUID, step_id: UUID) -> AutomationStep:
        copied: AutomationStep | None = None

        def copy(workflow: Workflow) -> Workflow:
            nonlocal copied
            steps = list(workflow.steps)
            index = next((index for index, step in enumerate(steps) if step.id == step_id), None)
            if index is None:
                raise KeyError(step_id)
            copied = clone_step(steps[index])
            steps.insert(index + 1, copied)
            return Workflow(id=workflow.id, name=workflow.name, steps=steps)

        self._replace_workflow(workflow_id, copy)
        assert copied is not None
        return copied

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
        self.historyChanged.emit(self.can_undo)

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

    def move_workflow_to_group(self, workflow_id: UUID, target_group_id: UUID) -> None:
        workflow: Workflow | None = None
        source_group_id: UUID | None = None
        if not any(group.id == target_group_id for group in self.project.groups):
            raise KeyError(target_group_id)
        for group in self.project.groups:
            for candidate in group.workflows:
                if candidate.id == workflow_id:
                    workflow = candidate
                    source_group_id = group.id
                    break
        if workflow is None or source_group_id is None:
            raise KeyError(workflow_id)
        if source_group_id == target_group_id:
            return
        groups: list[FlowGroup] = []
        for group in self.project.groups:
            workflows = [item for item in group.workflows if item.id != workflow_id]
            if group.id == target_group_id:
                workflows.append(workflow)
            groups.append(FlowGroup(id=group.id, name=group.name, workflows=workflows))
        self._commit(self.project.model_copy(update={"groups": groups}))

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
        self.historyChanged.emit(True)

from collections.abc import Mapping
from uuid import UUID, uuid4

from flow_runner.domain.project import AutomationStep, FlowGroup, Workflow
from flow_runner.domain.routing import RoutePredicate, RouteRule


def clone_step(step: AutomationStep) -> AutomationStep:
    step_ids = {step.id: uuid4()}
    return _clone_step(
        step,
        workflow_ids={},
        step_ids=step_ids,
        name=_copy_name(step.name),
    )


def clone_workflow(workflow: Workflow) -> Workflow:
    workflow_ids = {workflow.id: uuid4()}
    step_ids = {step.id: uuid4() for step in workflow.steps}
    return _clone_workflow(
        workflow,
        workflow_ids=workflow_ids,
        step_ids=step_ids,
        name=_copy_name(workflow.name),
    )


def clone_group(group: FlowGroup) -> FlowGroup:
    workflow_ids = {workflow.id: uuid4() for workflow in group.workflows}
    step_ids = {step.id: uuid4() for workflow in group.workflows for step in workflow.steps}
    workflows = [
        _clone_workflow(
            workflow,
            workflow_ids=workflow_ids,
            step_ids=step_ids,
            name=workflow.name,
        )
        for workflow in group.workflows
    ]
    return group.model_copy(
        deep=True,
        update={"id": uuid4(), "name": _copy_name(group.name), "workflows": workflows},
    )


def _clone_workflow(
    workflow: Workflow,
    *,
    workflow_ids: Mapping[UUID, UUID],
    step_ids: Mapping[UUID, UUID],
    name: str,
) -> Workflow:
    steps = [
        _clone_step(
            step,
            workflow_ids=workflow_ids,
            step_ids=step_ids,
            name=step.name,
        )
        for step in workflow.steps
    ]
    return workflow.model_copy(
        deep=True,
        update={"id": workflow_ids[workflow.id], "name": name, "steps": steps},
    )


def _clone_step(
    step: AutomationStep,
    *,
    workflow_ids: Mapping[UUID, UUID],
    step_ids: Mapping[UUID, UUID],
    name: str,
) -> AutomationStep:
    routes = [
        _remap_route(route, workflow_ids=workflow_ids, step_ids=step_ids) for route in step.routes
    ]
    return step.model_copy(
        deep=True,
        update={"id": step_ids[step.id], "name": name, "routes": routes},
    )


def _remap_route(
    route: RouteRule,
    *,
    workflow_ids: Mapping[UUID, UUID],
    step_ids: Mapping[UUID, UUID],
) -> RouteRule:
    target = route.target
    target_updates: dict[str, UUID] = {}
    if target.workflow_id in workflow_ids:
        assert target.workflow_id is not None
        target_updates["workflow_id"] = workflow_ids[target.workflow_id]
    if target.step_id in step_ids:
        assert target.step_id is not None
        target_updates["step_id"] = step_ids[target.step_id]
    remapped_target = target.model_copy(deep=True, update=target_updates)
    predicate = _remap_predicate(
        route.predicate,
        workflow_ids=workflow_ids,
        step_ids=step_ids,
    )
    return route.model_copy(
        deep=True,
        update={"target": remapped_target, "predicate": predicate},
    )


def _remap_predicate(
    predicate: RoutePredicate | None,
    *,
    workflow_ids: Mapping[UUID, UUID],
    step_ids: Mapping[UUID, UUID],
) -> RoutePredicate | None:
    if predicate is None:
        return None
    mapping: Mapping[UUID, UUID]
    if predicate.source == "workflow_count":
        mapping = workflow_ids
    elif predicate.source == "step_count":
        mapping = step_ids
    else:
        return predicate.model_copy(deep=True)
    try:
        referenced_id = UUID(predicate.key)
    except ValueError:
        return predicate.model_copy(deep=True)
    remapped_id = mapping.get(referenced_id)
    if remapped_id is None:
        return predicate.model_copy(deep=True)
    return predicate.model_copy(deep=True, update={"key": str(remapped_id)})


def _copy_name(name: str) -> str:
    return f"{name} 副本"

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flow_runner.domain.actions import ActionSpec
from flow_runner.domain.conditions import ConditionGroup, ConditionNode
from flow_runner.domain.project import AutomationStep, Project
from flow_runner.infrastructure.persistence.project_store import ProjectStore


@dataclass(frozen=True, slots=True)
class MigrationEntry:
    source: Path
    destination: Path
    category: str


@dataclass(frozen=True, slots=True)
class DataDirectoryMigrationPlan:
    root: Path
    staging_directory: Path
    data_directory: Path
    entries: tuple[MigrationEntry, ...]
    resource_targets: dict[Path, Path]


def build_migration_plan(root: Path) -> DataDirectoryMigrationPlan:
    root = root.resolve()
    data_directory = root / "data"
    staging_directory = root / ".plan_b_migration_staging"
    for occupied in (data_directory, staging_directory):
        if occupied.exists():
            raise FileExistsError(f"migration destination already exists: {occupied}")

    project_file = root / "project.json"
    if not project_file.is_file():
        raise FileNotFoundError(f"activity project does not exist: {project_file}")
    project = ProjectStore(project_file).load()
    entries: dict[Path, MigrationEntry] = {}
    resource_targets: dict[Path, Path] = {}

    def add(
        source: Path,
        destination: Path,
        category: str,
        *,
        resource: bool = False,
    ) -> None:
        source = source.resolve()
        destination = destination.resolve()
        if not source.is_file():
            return
        existing = entries.get(source)
        if existing is not None and existing.destination != destination:
            raise ValueError(f"migration source has multiple destinations: {source}")
        entries[source] = MigrationEntry(source, destination, category)
        if resource:
            resource_targets[source] = destination

    add(project_file, data_directory / "project.json", "project")
    for backup in sorted(root.glob("project.*.bak.json")):
        add(backup, data_directory / "backups" / backup.name, "backup")
    _add_tree(entries, resource_targets, root / "logs", data_directory / "logs", "log")
    _add_tree(
        entries,
        resource_targets,
        root / "templates",
        data_directory / "templates",
        "template",
        resources=True,
    )
    _add_tree(
        entries,
        resource_targets,
        root / "recordings",
        data_directory / "recordings",
        "recording",
        resources=True,
    )

    add(
        root / "config" / "flow_runner.json",
        data_directory / "legacy" / "config" / "flow_runner.json",
        "legacy_config",
    )
    scripts = root / "scripts"
    if scripts.is_dir():
        for script in sorted(scripts.glob("*.json")):
            add(
                script,
                data_directory / "legacy" / "scripts" / script.name,
                "legacy_script",
            )
    active_script_images = {scripts / "转职挑战.png", scripts / "存档.png"}
    active_script_images.update(_referenced_script_images(project, root))
    for image in sorted(active_script_images):
        add(
            image,
            data_directory / "templates" / "legacy" / image.name,
            "template",
            resource=True,
        )

    return DataDirectoryMigrationPlan(
        root=root,
        staging_directory=staging_directory,
        data_directory=data_directory,
        entries=tuple(
            sorted(entries.values(), key=lambda entry: str(entry.destination).casefold())
        ),
        resource_targets=resource_targets,
    )


def rewrite_condition(
    node: ConditionNode,
    targets: dict[Path, Path],
    root: Path,
) -> ConditionNode:
    if isinstance(node, ConditionGroup):
        return node.model_copy(
            update={
                "children": [rewrite_condition(child, targets, root) for child in node.children]
            }
        )
    if node.capability != "vision.image" or "template_path" not in node.config:
        return node
    config = dict(node.config)
    config["template_path"] = rewritten_resource_path(config["template_path"], targets, root)
    return node.model_copy(update={"config": config})


def rewrite_actions(
    actions: list[ActionSpec],
    targets: dict[Path, Path],
    root: Path,
) -> list[ActionSpec]:
    rewritten: list[ActionSpec] = []
    for action in actions:
        if action.capability != "recording.playback" or "path" not in action.config:
            rewritten.append(action)
            continue
        config = dict(action.config)
        config["path"] = rewritten_resource_path(config["path"], targets, root)
        rewritten.append(action.model_copy(update={"config": config}))
    return rewritten


def rewrite_step(
    step: AutomationStep,
    targets: dict[Path, Path],
    root: Path,
) -> AutomationStep:
    condition = (
        rewrite_condition(step.condition, targets, root) if step.condition is not None else None
    )
    condition_policy = step.condition_policy.model_copy(
        update={
            "before_attempt_actions": rewrite_actions(
                step.condition_policy.before_attempt_actions,
                targets,
                root,
            ),
            "after_no_match_actions": rewrite_actions(
                step.condition_policy.after_no_match_actions,
                targets,
                root,
            ),
        }
    )
    return step.model_copy(
        update={
            "condition": condition,
            "actions": rewrite_actions(step.actions, targets, root),
            "condition_policy": condition_policy,
        }
    )


def rewrite_project_resources(
    project: Project,
    targets: dict[Path, Path],
    root: Path,
) -> Project:
    groups = [
        group.model_copy(
            update={
                "workflows": [
                    workflow.model_copy(
                        update={
                            "steps": [rewrite_step(step, targets, root) for step in workflow.steps]
                        }
                    )
                    for workflow in group.workflows
                ]
            }
        )
        for group in project.groups
    ]
    return project.model_copy(update={"groups": groups})


def rewritten_resource_path(
    value: Any,
    targets: dict[Path, Path],
    root: Path,
) -> Any:
    source = Path(str(value))
    if not source.is_absolute():
        source = root / source
    target = targets.get(source.resolve())
    return str(target) if target is not None else value


def execute_migration(plan: DataDirectoryMigrationPlan) -> None:
    if plan.data_directory.exists():
        raise FileExistsError(f"migration destination already exists: {plan.data_directory}")
    if plan.staging_directory.exists():
        raise FileExistsError(
            f"migration staging directory already exists: {plan.staging_directory}"
        )
    staged_data = plan.staging_directory / "data"
    try:
        staged_data.mkdir(parents=True)
        for entry in plan.entries:
            relative = entry.destination.relative_to(plan.root)
            staged_target = plan.staging_directory / relative
            staged_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(entry.source, staged_target)

        staged_project = staged_data / "project.json"
        project = Project.model_validate_json(staged_project.read_text(encoding="utf-8"))
        rewritten = rewrite_project_resources(project, plan.resource_targets, plan.root)
        staged_project.write_text(
            rewritten.model_dump_json(indent=2),
            encoding="utf-8",
            newline="\n",
        )
        validated = Project.model_validate_json(staged_project.read_text(encoding="utf-8"))
        reference_errors = validated.validate_references()
        if reference_errors:
            raise ValueError("invalid migrated project references: " + "; ".join(reference_errors))
        _validate_migrated_resources(validated, plan)
        staged_data.replace(plan.data_directory)
        plan.staging_directory.rmdir()
    except Exception:
        if plan.staging_directory.exists():
            shutil.rmtree(plan.staging_directory)
        raise


def _add_tree(
    entries: dict[Path, MigrationEntry],
    resource_targets: dict[Path, Path],
    source_directory: Path,
    destination_directory: Path,
    category: str,
    *,
    resources: bool = False,
) -> None:
    if not source_directory.is_dir():
        return
    for source in sorted(path for path in source_directory.rglob("*") if path.is_file()):
        resolved_source = source.resolve()
        destination = (destination_directory / source.relative_to(source_directory)).resolve()
        entries[resolved_source] = MigrationEntry(resolved_source, destination, category)
        if resources:
            resource_targets[resolved_source] = destination


def _referenced_script_images(project: Project, root: Path) -> set[Path]:
    scripts = (root / "scripts").resolve()
    images: set[Path] = set()
    for value in _project_resource_values(project):
        candidate = Path(str(value))
        if not candidate.is_absolute():
            candidate = root / candidate
        candidate = candidate.resolve()
        if candidate.parent == scripts and candidate.suffix.casefold() == ".png":
            images.add(candidate)
    return images


def _project_resource_values(project: Project) -> list[Any]:
    values: list[Any] = []

    def condition_values(node: ConditionNode) -> None:
        if isinstance(node, ConditionGroup):
            for child in node.children:
                condition_values(child)
        elif node.capability == "vision.image" and "template_path" in node.config:
            values.append(node.config["template_path"])

    def action_values(actions: list[ActionSpec]) -> None:
        for action in actions:
            if action.capability == "recording.playback" and "path" in action.config:
                values.append(action.config["path"])

    for group in project.groups:
        for workflow in group.workflows:
            for step in workflow.steps:
                if step.condition is not None:
                    condition_values(step.condition)
                action_values(step.actions)
                action_values(step.condition_policy.before_attempt_actions)
                action_values(step.condition_policy.after_no_match_actions)
    return values


def _validate_migrated_resources(
    project: Project,
    plan: DataDirectoryMigrationPlan,
) -> None:
    destinations = {path.resolve() for path in plan.resource_targets.values()}
    for value in _project_resource_values(project):
        resource = Path(str(value))
        if not resource.is_absolute():
            resource = plan.root / resource
        resource = resource.resolve()
        if resource in destinations:
            staged = plan.staging_directory / resource.relative_to(plan.root)
            if not staged.is_file():
                raise FileNotFoundError(f"migrated resource is missing: {resource}")
        elif not resource.is_file():
            raise FileNotFoundError(f"project resource is missing: {resource}")

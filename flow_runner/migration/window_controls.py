from __future__ import annotations

import ntpath
from pathlib import Path
from typing import Any

from flow_runner.domain.actions import ActionSpec
from flow_runner.domain.project import AutomationStep, FlowGroup, Project, Workflow


def replacement_actions_for_script(script_path: Path) -> tuple[ActionSpec, ...] | None:
    name = ntpath.basename(str(script_path)).casefold()
    if name == "min_lanren.py":
        return (_window_action("minimize", "lanren2.exe"),)
    if name == "restore_lanren.py":
        return (_window_action("activate", "lanren2.exe"),)
    if name == "min.py":
        return (
            _window_action("minimize", "war3.exe", ["warcraft iii.exe"]),
            ActionSpec(capability="system.wait", config={"seconds": 0.3}),
            _window_action(
                "activate",
                "chrome.exe",
                ["PotPlayerMini64.exe", "potplayer.exe"],
            ),
        )
    if name == "restore.py":
        return (_window_action("activate", "war3.exe", ["warcraft iii.exe"]),)
    if name == "restore_platform.py":
        return (_window_action("activate", "platform.exe"),)
    return None


def migrate_project_window_control_actions(project: Project) -> Project:
    groups: list[FlowGroup] = []
    for group in project.groups:
        workflows: list[Workflow] = []
        for workflow in group.workflows:
            steps = [_migrate_step(step) for step in workflow.steps]
            workflows.append(workflow.model_copy(update={"steps": steps}))
        groups.append(group.model_copy(update={"workflows": workflows}))
    return project.model_copy(update={"groups": groups})


def count_window_control_scripts(project: Project) -> dict[str, int]:
    counts: dict[str, int] = {}
    for group in project.groups:
        for workflow in group.workflows:
            for step in workflow.steps:
                for action in step.actions:
                    script_name = _launch_script_name(action)
                    if (
                        script_name is not None
                        and replacement_actions_for_script(Path(script_name)) is not None
                    ):
                        counts[script_name] = counts.get(script_name, 0) + 1
    return counts


def _migrate_step(step: AutomationStep) -> AutomationStep:
    actions: list[ActionSpec] = []
    changed = False
    for action in step.actions:
        script_name = _launch_script_name(action)
        replacement = (
            replacement_actions_for_script(Path(script_name)) if script_name is not None else None
        )
        if replacement is None:
            actions.append(action)
        else:
            actions.extend(replacement)
            changed = True
    return step.model_copy(update={"actions": actions}) if changed else step


def _launch_script_name(action: ActionSpec) -> str | None:
    if action.capability != "system.launch":
        return None
    arguments = action.config.get("arguments")
    if not isinstance(arguments, (list, tuple)) or not arguments:
        return None
    first = arguments[0]
    return str(first) if isinstance(first, (str, Path)) else None


def _window_action(
    operation: str,
    process_name: str,
    fallback_process_names: list[str] | None = None,
) -> ActionSpec:
    config: dict[str, Any] = {
        "operation": operation,
        "process_name": process_name,
    }
    if fallback_process_names:
        config["fallback_process_names"] = fallback_process_names
    return ActionSpec(capability="system.window_action", config=config)

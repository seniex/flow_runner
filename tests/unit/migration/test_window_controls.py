import subprocess
import sys
from pathlib import Path

from flow_runner.domain.actions import ActionSpec
from flow_runner.domain.project import AutomationStep, FlowGroup, Project, Workflow
from flow_runner.migration.window_controls import (
    count_window_control_scripts,
    migrate_project_window_control_actions,
    replacement_actions_for_script,
)


def capabilities(actions):
    return [(action.capability, action.config) for action in actions]


def test_min_lanren_maps_to_minimize_lanren2():
    actions = replacement_actions_for_script(Path(r"D:\3eyes\Python\min_lanren.py"))

    assert capabilities(actions) == [
        ("system.window_action", {"operation": "minimize", "process_name": "lanren2.exe"})
    ]


def test_restore_lanren_maps_to_activate_lanren2():
    actions = replacement_actions_for_script(Path(r"D:\3eyes\Python\RESTORE_lanren.py"))

    assert capabilities(actions) == [
        ("system.window_action", {"operation": "activate", "process_name": "lanren2.exe"})
    ]


def test_min_maps_to_war3_minimize_wait_03_and_chrome_activation():
    actions = replacement_actions_for_script(Path(r"D:\3eyes\Python\min.py"))

    assert capabilities(actions) == [
        (
            "system.window_action",
            {
                "operation": "minimize",
                "process_name": "war3.exe",
                "fallback_process_names": ["warcraft iii.exe"],
            },
        ),
        ("system.wait", {"seconds": 0.3}),
        (
            "system.window_action",
            {
                "operation": "activate",
                "process_name": "chrome.exe",
                "fallback_process_names": ["PotPlayerMini64.exe", "potplayer.exe"],
            },
        ),
    ]


def test_restore_maps_to_war3_activation_with_warcraft_fallback():
    actions = replacement_actions_for_script(Path(r"D:\3eyes\Python\RESTORE.py"))

    assert capabilities(actions) == [
        (
            "system.window_action",
            {
                "operation": "activate",
                "process_name": "war3.exe",
                "fallback_process_names": ["warcraft iii.exe"],
            },
        )
    ]


def test_restore_platform_maps_to_platform_activation():
    actions = replacement_actions_for_script(Path(r"D:\3eyes\Python\restore_platform.py"))

    assert capabilities(actions) == [
        ("system.window_action", {"operation": "activate", "process_name": "platform.exe"})
    ]


def test_unknown_scripts_and_recordings_are_unchanged():
    assert replacement_actions_for_script(Path(r"D:\3eyes\Python\pet_explore.pyw")) is None
    assert replacement_actions_for_script(Path(r"D:\3eyes\Python\亮屏.json")) is None


def test_project_migration_preserves_ids_routes_existing_waits_and_non_window_launches():
    first = AutomationStep(
        name="最小化war3",
        actions=[
            ActionSpec(
                capability="system.launch",
                config={
                    "path": r"C:\Python\python.exe",
                    "arguments": [r"D:\3eyes\Python\min.py"],
                },
            ),
            ActionSpec(capability="system.wait", config={"seconds": 3.0}),
        ],
    )
    second = AutomationStep(
        name="保留脚本",
        actions=[
            ActionSpec(
                capability="system.launch",
                config={
                    "path": r"C:\Python\pythonw.exe",
                    "arguments": [r"D:\3eyes\Python\pet_explore.pyw"],
                },
            )
        ],
    )
    workflow = Workflow(name="main", steps=[first, second])
    project = Project(name="p", groups=[FlowGroup(name="g", workflows=[workflow])])

    migrated = migrate_project_window_control_actions(project)
    migrated_workflow = migrated.groups[0].workflows[0]
    migrated_first, migrated_second = migrated_workflow.steps

    assert migrated_first.id == first.id
    assert migrated_second.id == second.id
    assert [action.capability for action in migrated_first.actions] == [
        "system.window_action",
        "system.wait",
        "system.window_action",
        "system.wait",
    ]
    assert migrated_first.actions[1].config == {"seconds": 0.3}
    assert migrated_first.actions[3].config == {"seconds": 3.0}
    assert migrated_second.actions == second.actions


def test_window_control_migration_cli_is_dry_run_until_apply(tmp_path):
    project_path = tmp_path / "project.json"
    project = Project(
        name="p",
        groups=[
            FlowGroup(
                name="g",
                workflows=[
                    Workflow(
                        name="w",
                        steps=[
                            AutomationStep(
                                name="min",
                                actions=[
                                    ActionSpec(
                                        capability="system.launch",
                                        config={
                                            "path": "python.exe",
                                            "arguments": [r"D:\3eyes\Python\min.py"],
                                        },
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        ],
    )
    project_path.write_text(project.model_dump_json(indent=2), encoding="utf-8")
    original = project_path.read_bytes()

    dry_run = subprocess.run(
        [
            sys.executable,
            "scripts/migrate_window_control_actions.py",
            "--project",
            str(project_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert dry_run.returncode == 0
    assert project_path.read_bytes() == original

    applied = subprocess.run(
        [
            sys.executable,
            "scripts/migrate_window_control_actions.py",
            "--project",
            str(project_path),
            "--apply",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    assert applied.returncode == 0, applied.stderr
    migrated = Project.model_validate_json(project_path.read_text(encoding="utf-8"))
    assert migrated.groups[0].workflows[0].steps[0].actions[0].capability == (
        "system.window_action"
    )
    assert migrated.groups[0].workflows[0].steps[0].actions[0].config == {
        "operation": "minimize",
        "process_name": "war3.exe",
        "fallback_process_names": ["warcraft iii.exe"],
    }
    assert count_window_control_scripts(migrated) == {}
    assert list((tmp_path / "backups").glob("project.*.bak.json"))

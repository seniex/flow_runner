import subprocess
import sys
from pathlib import Path

import pytest

from flow_runner.domain.actions import ActionSpec
from flow_runner.domain.enums import StepOutcome
from flow_runner.domain.policies import ConditionPolicy
from flow_runner.domain.project import AutomationStep, FlowGroup, Project, Workflow
from flow_runner.domain.routing import RouteRule, RouteTarget
from flow_runner.infrastructure.persistence.project_store import ProjectStore
from flow_runner.migration import data_directory
from flow_runner.migration.data_directory import (
    build_migration_plan,
    execute_migration,
    rewrite_project_resources,
)


def _source_project(root: Path) -> Project:
    template = root / "scripts" / "target.png"
    recording = root / "recordings" / "legacy" / "play.json"
    template.parent.mkdir(parents=True)
    recording.parent.mkdir(parents=True)
    template.write_bytes(b"template")
    recording.write_text("{}", encoding="utf-8")
    playback = ActionSpec(
        capability="recording.playback",
        config={"path": "recordings\\legacy\\play.json"},
    )
    step = AutomationStep(
        name="步骤",
        condition={
            "id": "image",
            "capability": "vision.image",
            "config": {"template_path": "scripts\\target.png"},
        },
        actions=[playback],
        condition_policy=ConditionPolicy(
            before_attempt_actions=[playback],
            after_no_match_actions=[playback],
        ),
        routes=[RouteRule(outcome=StepOutcome.SUCCESS, target=RouteTarget.end())],
    )
    project = Project(
        name="项目",
        groups=[FlowGroup(name="组", workflows=[Workflow(name="流程", steps=[step])])],
        settings={"marker": "keep"},
    )
    ProjectStore(root / "project.json").save(project)
    return project


def test_migration_plan_maps_resources_and_rewrites_only_known_paths(tmp_path):
    project = _source_project(tmp_path)

    plan = build_migration_plan(tmp_path)
    template_source = (tmp_path / "scripts" / "target.png").resolve()
    recording_source = (tmp_path / "recordings" / "legacy" / "play.json").resolve()

    assert (
        plan.resource_targets[template_source]
        == (tmp_path / "data" / "templates" / "legacy" / "target.png").resolve()
    )
    assert (
        plan.resource_targets[recording_source]
        == (tmp_path / "data" / "recordings" / "legacy" / "play.json").resolve()
    )

    rewritten = rewrite_project_resources(project, plan.resource_targets, tmp_path)
    original_step = project.groups[0].workflows[0].steps[0]
    rewritten_step = rewritten.groups[0].workflows[0].steps[0]

    assert rewritten.id == project.id
    assert rewritten.settings == project.settings
    assert rewritten_step.id == original_step.id
    assert rewritten_step.routes == original_step.routes
    assert rewritten_step.condition is not None
    assert rewritten_step.condition.config["template_path"] == str(
        plan.resource_targets[template_source]
    )
    assert rewritten_step.actions[0].config["path"] == str(plan.resource_targets[recording_source])
    assert rewritten_step.condition_policy.before_attempt_actions[0].config["path"] == str(
        plan.resource_targets[recording_source]
    )
    assert rewritten_step.condition_policy.after_no_match_actions[0].config["path"] == str(
        plan.resource_targets[recording_source]
    )


def test_execute_migration_stages_valid_data_without_deleting_sources(tmp_path):
    source = _source_project(tmp_path)
    plan = build_migration_plan(tmp_path)

    execute_migration(plan)

    migrated = ProjectStore(tmp_path / "data" / "project.json").load()
    assert migrated.id == source.id
    assert migrated.validate_references() == []
    assert (tmp_path / "project.json").is_file()
    assert (tmp_path / "scripts" / "target.png").is_file()
    assert (tmp_path / "recordings" / "legacy" / "play.json").is_file()
    assert (tmp_path / "data" / "templates" / "legacy" / "target.png").is_file()
    assert (tmp_path / "data" / "recordings" / "legacy" / "play.json").is_file()
    assert not (tmp_path / ".plan_b_migration_staging").exists()


def test_copy_failure_preserves_sources_and_removes_staging(tmp_path, monkeypatch):
    _source_project(tmp_path)
    plan = build_migration_plan(tmp_path)

    def fail_copy(_source, _destination):
        raise OSError("copy failed")

    monkeypatch.setattr(data_directory.shutil, "copy2", fail_copy)

    with pytest.raises(OSError, match="copy failed"):
        execute_migration(plan)

    assert (tmp_path / "project.json").exists()
    assert not (tmp_path / "data" / "project.json").exists()
    assert not (tmp_path / ".plan_b_migration_staging").exists()


@pytest.mark.parametrize("occupied", ["data", ".plan_b_migration_staging"])
def test_migration_plan_rejects_occupied_destination(tmp_path, occupied):
    _source_project(tmp_path)
    (tmp_path / occupied).mkdir()

    with pytest.raises(FileExistsError, match=occupied):
        build_migration_plan(tmp_path)


def test_migration_cli_can_run_as_a_direct_script():
    result = subprocess.run(
        [sys.executable, "scripts/migrate_plan_b_data.py", "--help"],
        cwd=Path.cwd(),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "--apply" in result.stdout

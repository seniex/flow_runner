import json
from pathlib import Path

import pytest

from flow_runner.domain.enums import StepOutcome
from flow_runner.domain.routing import RouteTargetKind
from flow_runner.infrastructure.input.recording import RecordingStore
from flow_runner.migration.legacy import (
    LegacyConversionPaths,
    convert_legacy_config,
    convert_legacy_recording,
)


def sample_legacy_config(tmp_path: Path) -> dict[str, object]:
    return {
        "ocr_engine": "paddle",
        "hotkey_start": "F11",
        "hotkey_stop": "F12",
        "hotkey_pause": "",
        "hotkey_rec_toggle": "F6",
        "flow_groups": [
            {
                "name": "组A",
                "flows": [
                    {
                        "name": "检测并点击",
                        "loop_count": 1,
                        "next_flow": 1,
                        "steps": [
                            {
                                "type": "ocr_click",
                                "name": "开始游戏",
                                "region": [10, 20, 110, 120],
                                "keywords": "开始游戏",
                                "ocr_scale": "2",
                                "language": "chi_sim",
                                "retry_interval": 0.5,
                                "max_retries": 3,
                                "jitter": True,
                                "click_actions": [
                                    {
                                        "pre_delay": 0.1,
                                        "pos_mode": "offset",
                                        "offset_x": 4,
                                        "offset_y": -2,
                                        "abs_x": 0,
                                        "abs_y": 0,
                                        "count": 1,
                                        "interval": 0.1,
                                        "click_type": "single",
                                    }
                                ],
                            },
                            {
                                "type": "run_script",
                                "name": "回放",
                                "script_path": str(tmp_path / "旧录制.json"),
                                "speed": 2.0,
                                "max_gap": 1.5,
                                "jitter_ms": 40,
                            },
                        ],
                    },
                    {
                        "name": "启动脚本",
                        "loop_count": 1,
                        "next_flow": -1,
                        "steps": [
                            {
                                "type": "launch_app",
                                "name": "启动",
                                "app_path": str(tmp_path / "helper.py"),
                                "run_as_admin": True,
                                "wait_seconds": 1.0,
                            }
                        ],
                    },
                ],
            }
        ],
    }


def test_legacy_conversion_preserves_conditions_actions_and_workflow_routes(tmp_path):
    project = convert_legacy_config(
        sample_legacy_config(tmp_path),
        LegacyConversionPaths(
            project_directory=tmp_path,
            python_executable=tmp_path / ".venv" / "python.exe",
            pythonw_executable=tmp_path / ".venv" / "pythonw.exe",
            paddle_executable=tmp_path / "PaddleOCR-json.exe",
            recording_directory=tmp_path / "recordings" / "legacy",
        ),
    )

    assert len(project.groups) == 1
    first, second = project.groups[0].workflows
    condition_step = first.steps[0]
    assert condition_step.condition is not None
    assert condition_step.condition.config["scale"] == 2.0
    assert condition_step.condition_policy.max_attempts == 4
    assert condition_step.actions[0].capability == "system.wait"
    click = condition_step.actions[1]
    assert click.config["position"] == "$result.primary.position"
    assert click.config["offset"] == [4, -2]
    assert click.config["jitter_pixels"] == 3
    assert click.config["duration"] == 0.015
    assert click.config["settle_delay"] == 0.015

    playback = first.steps[1].actions[0]
    assert str(playback.config["path"]).replace("\\", "/").endswith("recordings/legacy/旧录制.json")
    assert playback.config["jitter_ms"] == 40
    final_route = first.steps[-1].routes[0]
    assert final_route.outcome is StepOutcome.SUCCESS
    assert final_route.target.kind is RouteTargetKind.JUMP_WORKFLOW
    assert final_route.target.workflow_id == second.id

    launch_actions = second.steps[0].actions
    assert str(launch_actions[0].config["path"]).endswith("python.exe")
    assert launch_actions[0].config["arguments"] == [str(tmp_path / "helper.py")]
    assert launch_actions[0].config["run_as_admin"] is False
    assert launch_actions[0].config["hide_window"] is True
    assert launch_actions[1].config == {"seconds": 1.0}
    assert project.settings["hotkeys"] == {
        "start": "F11",
        "stop": "F12",
        "pause": "",
        "record": "F6",
    }


def test_legacy_recording_conversion_normalizes_time_and_click_pairs(tmp_path):
    events = convert_legacy_recording(
        [
            {"t": 2.0, "type": "move", "x": 10, "y": 20},
            {"t": 2.1, "type": "click", "x": 10, "y": 20, "btn": "left", "down": True},
            {"t": 2.2, "type": "click", "x": 10, "y": 20, "btn": "left", "down": False},
            {"t": 2.3, "type": "scroll", "x": 10, "y": 20, "dx": 0, "dy": -2},
        ]
    )
    output = tmp_path / "recording.json"
    RecordingStore.save(output, events)
    loaded = RecordingStore.load(output)

    assert [event.kind for event in loaded] == ["move", "click", "scroll"]
    assert [event.timestamp for event in loaded] == pytest.approx([0.0, 0.1, 0.3])
    assert loaded[1].data == {"x": 10, "y": 20, "button": "left"}
    assert loaded[2].data["units"] == -240


def test_legacy_conversion_replaces_known_window_control_scripts(tmp_path):
    source = {
        "flow_groups": [
            {
                "name": "组",
                "flows": [
                    {
                        "name": "流程",
                        "steps": [
                            {
                                "type": "launch_app",
                                "app_path": str(tmp_path / "min.py"),
                            }
                        ],
                    }
                ],
            }
        ]
    }

    project = convert_legacy_config(
        source,
        LegacyConversionPaths(
            project_directory=tmp_path,
            python_executable=tmp_path / "python.exe",
            pythonw_executable=tmp_path / "pythonw.exe",
            paddle_executable=tmp_path / "PaddleOCR-json.exe",
            recording_directory=tmp_path / "recordings",
        ),
    )

    assert [action.capability for action in project.groups[0].workflows[0].steps[0].actions] == [
        "system.window_action",
        "system.wait",
        "system.window_action",
    ]


def test_full_legacy_fixture_converts_all_groups_workflows_and_steps():
    source = json.loads(Path("data/legacy/config/flow_runner.json").read_text(encoding="utf-8"))
    project = convert_legacy_config(
        source,
        LegacyConversionPaths(
            project_directory=Path.cwd(),
            python_executable=Path.cwd() / ".venv" / "Scripts" / "python.exe",
            pythonw_executable=Path.cwd() / ".venv" / "Scripts" / "pythonw.exe",
            paddle_executable=Path("D:/PaddleOCR-json.exe"),
            recording_directory=Path.cwd() / "data" / "recordings" / "legacy",
        ),
    )

    assert len(project.groups) == 4
    assert sum(len(group.workflows) for group in project.groups) == 99
    step_count = sum(
        len(workflow.steps) for group in project.groups for workflow in group.workflows
    )
    assert step_count == 159
    assert project.validate_references() == []

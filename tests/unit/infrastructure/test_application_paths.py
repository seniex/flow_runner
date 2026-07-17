from datetime import datetime

from flow_runner.infrastructure.paths import ApplicationPaths, timestamped_recording_file


def test_default_paths_put_all_runtime_data_under_data(tmp_path):
    paths = ApplicationPaths.default(tmp_path / "flow_runner")

    assert paths.project_file == tmp_path / "flow_runner" / "data" / "project.json"
    assert paths.backup_directory == tmp_path / "flow_runner" / "data" / "backups"
    assert paths.template_directory == tmp_path / "flow_runner" / "data" / "templates"
    assert paths.recording_directory == tmp_path / "flow_runner" / "data" / "recordings"
    assert paths.latest_recording_file == paths.recording_directory / "latest.json"
    assert paths.log_directory == tmp_path / "flow_runner" / "data" / "logs"
    assert paths.session_name == "flow_runner"


def test_explicit_project_keeps_test_data_beside_that_project(tmp_path):
    project_file = tmp_path / "custom" / "project.json"

    paths = ApplicationPaths.for_project(project_file)

    assert paths.project_file == project_file
    assert paths.backup_directory == project_file.parent / "backups"
    assert paths.template_directory == project_file.parent / "templates"
    assert paths.recording_directory == project_file.parent / "recordings"
    assert paths.log_directory == project_file.parent / "logs"
    assert paths.session_name == "custom"


def test_timestamped_recording_file_uses_save_time_and_avoids_collisions(tmp_path):
    saved_at = datetime(2026, 7, 17, 8, 33, 14)

    first = timestamped_recording_file(tmp_path, saved_at)
    first.touch()
    second = timestamped_recording_file(tmp_path, saved_at)
    second.touch()
    third = timestamped_recording_file(tmp_path, saved_at)

    assert first == tmp_path / "recording_20260717_083314.json"
    assert second == tmp_path / "recording_20260717_083314_2.json"
    assert third == tmp_path / "recording_20260717_083314_3.json"

from flow_runner.infrastructure.paths import ApplicationPaths


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

from uuid import uuid4

from PySide6.QtCore import QSettings

from flow_runner.ui.flow_tree_preferences import FlowTreePreferences


def test_flow_tree_preferences_round_trip_and_isolate_projects(tmp_path):
    settings = QSettings(str(tmp_path / "tree.ini"), QSettings.Format.IniFormat)
    preferences = FlowTreePreferences(settings)
    first_project = uuid4()
    second_project = uuid4()
    group_id = uuid4()

    preferences.set_collapsed_groups(first_project, {group_id})
    settings.sync()

    reopened = FlowTreePreferences(
        QSettings(str(tmp_path / "tree.ini"), QSettings.Format.IniFormat)
    )
    assert reopened.collapsed_groups(first_project) == frozenset({group_id})
    assert reopened.collapsed_groups(second_project) == frozenset()


def test_flow_tree_preferences_ignore_malformed_group_ids(tmp_path):
    project_id = uuid4()
    settings = QSettings(str(tmp_path / "tree.ini"), QSettings.Format.IniFormat)
    settings.setValue(
        f"flow_tree/{project_id}/collapsed_groups",
        ["bad-id", str(uuid4())],
    )

    assert len(FlowTreePreferences(settings).collapsed_groups(project_id)) == 1

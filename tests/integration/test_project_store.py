from unittest.mock import patch

import pytest

from flow_runner.domain.errors import ConfigurationError
from flow_runner.domain.project import Project
from flow_runner.infrastructure.persistence.project_store import ProjectStore


def test_project_store_round_trips_and_keeps_five_backups(tmp_path):
    path = tmp_path / "project.json"
    store = ProjectStore(path)
    for index in range(7):
        store.save(Project(name=f"project-{index}"))
    assert store.load().name == "project-6"
    assert len(list(tmp_path.glob("project.*.bak.json"))) == 5


def test_project_store_rejects_invalid_json(tmp_path):
    path = tmp_path / "project.json"
    path.write_text("{bad", encoding="utf-8")
    with pytest.raises(ConfigurationError, match="invalid project JSON"):
        ProjectStore(path).load()


def test_project_store_cleans_temporary_file_when_atomic_replace_fails(tmp_path):
    path = tmp_path / "project.json"
    store = ProjectStore(path)
    store.save(Project(name="original"))
    original = path.read_bytes()

    with patch(
        "flow_runner.infrastructure.persistence.project_store.os.replace",
        side_effect=OSError("replace failed"),
    ):
        with pytest.raises(OSError, match="replace failed"):
            store.save(Project(name="replacement"))

    assert path.read_bytes() == original
    assert not path.with_suffix(".json.tmp").exists()
